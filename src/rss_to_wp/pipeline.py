"""Collect broadly, group related sources, then publish only verified stories."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import pendulum

from rss_to_wp.config import AppSettings, FeedsConfig
from rss_to_wp.editorial import (
    Source,
    canonical_url,
    plain_text,
    story_slug,
    unavailable_source,
    unique_source_words,
    validate_article,
    validate_verification,
    word_count,
)
from rss_to_wp.feeds import (
    generate_entry_key,
    get_entry_content,
    get_entry_link,
    get_entry_title,
    parse_feed,
    pick_entries,
)
from rss_to_wp.feeds.filter import parse_entry_date
from rss_to_wp.images import download_image, find_rss_image
from rss_to_wp.utils import get_logger

logger = get_logger("pipeline")


def collect_sources(config: FeedsConfig, settings: AppSettings, store, hours: int, replay=False):
    sources, observations = [], []
    seen_urls, seen_content = set(), set()
    # Round-robin candidate selection avoids one busy feed starving local coverage.
    feed_sources = []
    errors = 0
    for feed_config in config.feeds:
        if not feed_config.enabled:
            continue
        candidates = []
        feed = parse_feed(feed_config.url)
        if feed is None:
            observations.append({"feed": feed_config.name, "outcome": "feed_error"})
            errors += 1
            continue
        entries = pick_entries(
            feed.entries,
            max_count=len(feed.entries),
            hours_window=hours,
            timezone=settings.timezone,
        )
        if not entries:
            observations.append({"feed": feed_config.name, "outcome": "no_recent_sources"})
        for entry in entries:
            title = plain_text(get_entry_title(entry))
            text = plain_text(get_entry_content(entry))
            if unavailable_source(title, text):
                observations.append({"title": title, "outcome": "unavailable_source"})
                continue
            link = get_entry_link(entry)
            try:
                url = canonical_url(link or "")
            except ValueError:
                observations.append({"title": title, "outcome": "invalid_source_url"})
                continue
            key = generate_entry_key(entry, feed_config.url)
            if url in seen_urls or (text and text.casefold() in seen_content):
                continue
            seen_urls.add(url)
            if text:
                seen_content.add(text.casefold())
            if not replay and store.is_published(key, url):
                observations.append({"title": title, "outcome": "duplicate"})
                continue
            # Keep tiny scoreboard updates and meaningful titles for grouping.
            if word_count(text + " " + title) < 5:
                observations.append({"title": title, "outcome": "no_usable_text"})
                continue
            candidates.append(
                Source(
                    id="",
                    key=key,
                    url=url,
                    title=title,
                    text=text[:16000],
                    published=pendulum.instance(parse_entry_date(entry))
                    .in_timezone(settings.timezone)
                    .isoformat(),
                    feed=feed_config,
                    entry=entry,
                )
            )
            if len(candidates) >= feed_config.max_candidates:
                break
        feed_sources.append(candidates)
    while any(feed_sources) and len(sources) < config.editorial.max_candidates:
        for candidates in feed_sources:
            if candidates and len(sources) < config.editorial.max_candidates:
                source = candidates.pop(0)
                source.id = f"s{len(sources) + 1}"
                sources.append(source)
    return sources, observations, errors


def make_groups(plan, sources, policy):
    """A planner cannot invent sources, reuse one across stories, or lose sources."""
    by_id = {s.id: s for s in sources}
    seen, groups = set(), []
    for group in plan.groups:
        ids = group.source_ids
        if not ids or len(ids) > policy.max_group_sources:
            raise ValueError("Invalid story group size")
        if len(set(ids)) != len(ids) or any(i not in by_id or i in seen for i in ids):
            raise ValueError("Planner returned unknown or reused source IDs")
        members = [by_id[i] for i in ids]
        dates = [pendulum.parse(s.published) for s in members]
        if (max(dates) - min(dates)).total_hours() > policy.cluster_hours:
            raise ValueError("Story group crosses the editorial time window")
        groups.append(members)
        seen.update(ids)
    # Omitted inputs are assessed singly, never silently discarded.
    groups.extend([[s] for s in sources if s.id not in seen])
    return groups


def upload_source_image(sources, wp):
    """A missing image must not crash a valid story. No unrelated stock photos."""
    for source in sorted(sources, key=lambda s: s.published, reverse=True):
        url = find_rss_image(source.entry, base_url=source.url)
        if not url:
            continue
        result = download_image(url)
        if result:
            image_bytes, filename, _ = result
            return wp.upload_media(
                image_bytes=image_bytes,
                filename=filename,
                alt_text="Image supplied by " + (source.feed.source_name or source.feed.name),
            )
    return None


def run_pipeline(
    config: FeedsConfig,
    settings: AppSettings,
    store,
    editor,
    wp=None,
    dry_run=False,
    hours=72,
    replay=False,
    report_dir=Path("data"),
):
    if replay and not dry_run:
        raise ValueError("Replay is allowed only with --dry-run")
    policy = config.editorial
    sources, observations, errors = collect_sources(config, settings, store, hours, replay)
    report = {
        "dry_run": dry_run,
        "replay": replay,
        "candidate_sources": len(sources),
        "published": 0,
        "eligible": 0,
        "held": 0,
        "duplicates": 0,
        "errors": errors,
        "feed_observations": observations,
        "stories": [],
    }
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "editorial_version": 1,
                "model": settings.openai_model,
                "policy": policy.model_dump(),
                "sources": [s.payload() for s in sources],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    try:
        if not sources:
            return report
        if not dry_run and not errors and store.recently_held(fingerprint, time.time()):
            report["unchanged_sources"] = True
            return report
        plan = editor.plan(sources)
        report["plan"] = plan.model_dump()
        try:
            groups = make_groups(plan, sources, policy)
        except ValueError as error:
            report["planning_warning"] = str(error)
            plan = editor.plan(sources, feedback=str(error))
            report["revised_plan"] = plan.model_dump()
            try:
                groups = make_groups(plan, sources, policy)
            except ValueError as error:
                # Salvage valid groups instead of losing all combined coverage.
                report["planning_warning"] += "; revision: " + str(error)
                groups, used = [], set()
                for proposed in plan.groups:
                    try:
                        single_plan = type(plan)(groups=[proposed])
                        members = make_groups(single_plan, sources, policy)[0]
                        if any(s.id in used for s in members):
                            continue
                    except ValueError:
                        continue
                    groups.append(members)
                    used.update(s.id for s in members)
                groups.extend([[s] for s in sources if s.id not in used])
        day_start = (
            pendulum.now(settings.timezone)
            .start_of("day")
            .in_timezone("UTC")
            .to_iso8601_string()
            .replace("Z", "")
        )
        published_today = store.posts_since(day_start)
        feed_counts = Counter()
        for group in groups:
            row = {
                "source_urls": [s.url for s in group],
                "source_titles": [s.title for s in group],
                "source_words": unique_source_words(group),
            }
            report["stories"].append(row)
            if row["source_words"] < policy.min_source_words:
                row.update(outcome="hold", reasons=["not_enough_source_information"])
                report["held"] += 1
                continue
            try:
                article = editor.rewrite_story(group, policy)
                row.update(article=article.model_dump(), body_words=word_count(article.body))
                problems = validate_article(article, group, policy)
                if not problems:
                    verification = editor.verify(article, group)
                    row["verification"] = verification.model_dump()
                    if not validate_verification(verification):
                        problems = ["verification_failed", *verification.issues]
                if problems and article.decision == "publish":
                    row["initial_rejection"] = problems
                    if "verification" in row:
                        row["initial_verification"] = row.pop("verification")
                    article = editor.repair(article, group, policy, problems)
                    row.update(article=article.model_dump(), body_words=word_count(article.body))
                    problems = validate_article(article, group, policy)
                    if not problems:
                        verification = editor.verify(article, group)
                        row["verification"] = verification.model_dump()
                        if not validate_verification(verification):
                            problems = ["verification_failed", *verification.issues]
                if problems:
                    row.update(outcome="hold", reasons=problems)
                    report["held"] += 1
                    continue
                report["eligible"] += 1
                if dry_run:
                    row.update(outcome="would_publish")
                    continue
                # Only credit, illustrate and consume the sources actually used.
                group = [s for s in group if s.id in article.source_ids]
                if wp is None:
                    raise ValueError("WordPress client required to publish")
                group_feeds = {s.feed.name: s.feed for s in group}
                if (
                    report["published"] >= policy.max_posts_per_run
                    or published_today + report["published"] >= policy.max_posts_per_day
                    or any(feed_counts[name] >= f.max_per_run for name, f in group_feeds.items())
                ):
                    row.update(outcome="deferred", reasons=["publication_budget"])
                    continue
                # Check BEFORE uploading media or creating taxonomies; DB cache is not authoritative.
                existing = next(
                    (post for s in group if (post := wp.find_post_by_source(s.url))), None
                )
                if existing:
                    row.update(outcome="duplicate", post_url=existing.get("link"))
                    report["duplicates"] += 1
                    # Do not consume additional unpublished sources from this mixed group.
                    continue
                category = group[0].feed.default_category
                category_id = wp.get_or_create_category(category) if category else None
                if category and not category_id:
                    raise RuntimeError("Required category could not be resolved")
                tag_ids = wp.get_or_create_tags(
                    sorted({tag for s in group for tag in s.feed.default_tags})
                )
                media_id = upload_source_image(group, wp)
                # Human-readable, stable within a source group; fallback duplicate checks survive cache eviction.
                slug = wp._slugify(article.headline)[:130] + "-" + story_slug(group)[3:15]
                post = wp.create_post(
                    title=article.headline,
                    content=article.body,
                    excerpt=article.excerpt,
                    category_id=category_id,
                    tag_ids=tag_ids,
                    featured_media_id=media_id,
                    sources=[
                        {"url": s.url, "name": s.feed.source_name or s.feed.name} for s in group
                    ],
                    slug=slug,
                )
                if not post or not post.get("id"):
                    raise RuntimeError("WordPress did not confirm the post")
                if post.get("already_exists"):
                    row.update(outcome="duplicate", post_url=post.get("link"))
                    report["duplicates"] += 1
                    continue
                for s in group:
                    store.mark_processed(
                        s.key, s.feed.url, s.title, s.url, post["id"], post.get("link")
                    )
                row.update(
                    outcome="published" if post.get("status") == "publish" else "saved",
                    post_url=post.get("link"),
                    post_id=post["id"],
                )
                report["published"] += 1
                feed_counts.update(group_feeds.keys())
            except Exception as error:
                row.update(outcome="error", reasons=[type(error).__name__])
                report["errors"] += 1
                logger.error("story_processing_error", error_type=type(error).__name__)
    except Exception as error:
        report["errors"] += 1
        report["fatal_error"] = type(error).__name__
        if type(error) is ValueError:
            report["fatal_reason"] = str(error)[:300]
        logger.error("pipeline_error", error_type=type(error).__name__)
    finally:
        if (
            not dry_run
            and sources
            and not report["errors"]
            and not report["eligible"]
            and not report.get("unchanged_sources")
        ):
            store.remember_held(fingerprint, time.time())
        report["zero_publication_warning"] = report["published"] == 0 and not dry_run
        (report_dir / "editorial-report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        summary = f"## Pontotoc editorial run\n\nCandidates: {len(sources)} · Eligible: {report['eligible']} · Published/saved: {report['published']} · Held: {report['held']} · Errors: {report['errors']}\n\n"
        if report["zero_publication_warning"]:
            summary += "No articles were published. Check source availability and hold reasons before adjusting the editorial policy. Do not fill the gap with invented details.\n\n"
        if report.get("unchanged_sources"):
            summary += "These unchanged sources were already held within six hours. Any new source or changed policy triggers fresh evaluation immediately.\n\n"
        for row in report["stories"]:
            title = row.get("article", {}).get("headline") or row["source_titles"][0]
            title = plain_text(title).replace("\n", " ")[:150]
            summary += f"- {row.get('outcome', 'unknown')}: {title} ({row.get('body_words', 0)} words) — {', '.join(row.get('reasons', []))}\n"
        (report_dir / "editorial-summary.md").write_text(summary, encoding="utf-8")
    return report
