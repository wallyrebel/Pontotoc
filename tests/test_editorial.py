from datetime import datetime, timezone
from time import struct_time
from unittest.mock import Mock

import feedparser
import pendulum
import pytest
import requests
from pydantic import ValidationError
from typer.testing import CliRunner

from rss_to_wp.cli import app
from rss_to_wp.config import AppSettings, EditorialPolicy, FeedConfig, FeedsConfig
from rss_to_wp.editorial import (
    Article,
    Source,
    StoryPlan,
    Verification,
    canonical_url,
    validate_article,
)
from rss_to_wp.feeds.filter import is_within_window, parse_entry_date
from rss_to_wp.pipeline import collect_sources, make_groups, run_pipeline
from rss_to_wp.rewriter import OpenAIRewriter
from rss_to_wp.storage import DedupeStore
from rss_to_wp.wordpress import WordPressClient

TEXT = (
    "Pontotoc Community Theater will present The Butler Did It on October 9 at 7 p.m. "
    "Additional performances are October 10 at 2 p.m. and 7 p.m., and October 11 at 2 p.m. "
    "Tickets cost $10 and are available online through Zeffy. Tickets are also available "
    "at the door 30 minutes before each performance. The production is a comedic murder "
    "mystery at Pontotoc Community Theater. Brian will make his stage debut as Colonel "
    "Nigel Covington. Ashh Patterson plays Father Timothy in his fifth production with "
    "the theater. His previous credits include Artist Retreat, The Murder Mystery at The "
    "Murder Mystery, Sherlock Holmes and Treasure Island. Jon Butler plays Jenkins, "
    "the butler. He has a decade of theater experience and appeared in Treasure Island "
    "in the spring. The theater announced the cast and ticket information to help "
    "audiences plan their visit to the upcoming production."
)


@pytest.fixture
def cfg():
    return FeedsConfig(
        feeds=[
            FeedConfig(
                name="Local", url="https://example.org/rss", default_category="Pontotoc News"
            )
        ]
    )


@pytest.fixture
def settings():
    return AppSettings(
        _env_file=None,
        openai_api_key="test",
        wordpress_base_url="https://example.org",
        wordpress_username="test",
        wordpress_app_password="test",
    )


@pytest.fixture
def source(cfg):
    return Source(
        "s1",
        "id:1",
        "https://example.org/story",
        "The Butler Did It performances",
        TEXT,
        pendulum.now("America/Chicago").isoformat(),
        cfg.feeds[0],
        {},
    )


@pytest.fixture
def article(source):
    def evidence(quote):
        return dict(answer=quote, source_id="s1", quote=quote)

    ws = dict(
        who=evidence("Pontotoc Community Theater"),
        what=evidence("present The Butler Did It"),
        where=evidence("at Pontotoc Community Theater"),
        when=evidence("October 9 at 7 p.m."),
        why=evidence("to help audiences plan their visit"),
    )
    # Three complete paragraphs, with enough source-supported text for a useful brief.
    body = (
        "<p>"
        + TEXT[: TEXT.index("The production")]
        + "</p><p>"
        + TEXT[TEXT.index("The production") : TEXT.index("Jon Butler")]
        + "</p><p>"
        + TEXT[TEXT.index("Jon Butler") :]
        + "</p>"
    )
    return Article(
        decision="publish",
        reason="Complete event information",
        kind="brief",
        headline="Pontotoc theater announces October performances and ticket details",
        excerpt="Pontotoc Community Theater will present The Butler Did It in October, with tickets available online and at the door.",
        body=body,
        five_ws=ws,
        facts=list(ws.values()),
        source_ids=["s1"],
        local_relevance="Pontotoc theater event",
        brief_justification="Dates, venue, times and ticket details",
    )


@pytest.fixture
def approved():
    return Verification(
        approved=True,
        all_claims_supported=True,
        five_ws_in_body=True,
        same_event=True,
        locally_relevant=True,
        no_padding=True,
        no_unresolved_conflicts=True,
        issues=[],
    )


def fake_editor(article, approved):
    editor = Mock()
    editor.plan.return_value = StoryPlan.model_validate(
        {"groups": [{"source_ids": ["s1"], "reason": "one event"}]}
    )
    editor.rewrite_story.return_value = article
    editor.repair.return_value = article
    editor.verify.return_value = approved
    return editor


def test_useful_brief_passes_without_200_word_requirement(article, source):
    assert validate_article(article, [source], EditorialPolicy()) == []


def test_thin_or_unsupported_article_does_not_pass(article, source):
    article.body = "<p>Pontotoc won.</p>"
    article.five_ws.when.quote = "Invented date"
    problems = validate_article(article, [source], EditorialPolicy())
    assert "unsupported_evidence:when" in problems
    assert any(p.startswith("body_word_count") for p in problems)


def test_untrusted_generated_html_is_rejected(article, source):
    article.body += '<script>alert(1)</script><p onclick="x()">Extra.</p>'
    assert "unsafe_or_unexpected_html" in validate_article(article, [source], EditorialPolicy())


def test_five_ws_missing_is_invalid(article):
    payload = article.model_dump()
    del payload["five_ws"]["why"]
    with pytest.raises(ValidationError):
        Article.model_validate(payload)


def test_unknown_and_reused_group_sources_are_rejected(source):
    for ids in [["s1", "s1"], ["invented"]]:
        plan = StoryPlan.model_validate({"groups": [{"source_ids": ids, "reason": "x"}]})
        with pytest.raises(ValueError):
            make_groups(plan, [source], EditorialPolicy())


def test_omitted_source_still_gets_assessed(source):
    assert make_groups(StoryPlan(groups=[]), [source], EditorialPolicy()) == [[source]]


def test_future_sources_do_not_pass_freshness_gate():
    assert not is_within_window(pendulum.now("UTC").add(days=10))


def test_feedparser_utc_date_is_not_interpreted_as_local_time():
    value = struct_time((2026, 10, 1, 22, 30, 0, 3, 274, 0))
    assert parse_entry_date({"published_parsed": value}) == datetime(
        2026, 10, 1, 22, 30, tzinfo=timezone.utc
    )


def test_config_honors_legacy_category_and_disabled_feeds():
    feed = FeedConfig(
        name="x", url="https://example.org/rss", category="Pontotoc News", enabled=False
    )
    assert feed.default_category == "Pontotoc News"
    assert not feed.enabled
    with pytest.raises(ValidationError):
        FeedConfig(name="x", url="https://example.org", max_per_rnu=3)


def test_tracking_urls_share_identity_without_losing_story_id():
    assert (
        canonical_url("https://example.org/story/?utm_source=x&fbclid=y")
        == "https://example.org/story"
    )
    assert canonical_url("https://facebook.com/story.php?story_fbid=123&id=5") != canonical_url(
        "https://facebook.com/story.php?story_fbid=124&id=5"
    )


def test_dry_run_and_legacy_dry_run_rows_never_consume_a_story(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    store = DedupeStore(tmp_path / "processed.db")
    store.mark_processed(
        "id:1", cfg.feeds[0].url, source.title, source.url, 0, "dry-run://not-published"
    )
    assert not store.is_published(source.key, source.url)
    before = (tmp_path / "processed.db").read_bytes()
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source], [], 0))
    wp = Mock()
    report = run_pipeline(
        cfg, settings, store, fake_editor(article, approved), wp, dry_run=True, report_dir=tmp_path
    )
    assert report["eligible"] == 1 and report["published"] == 0
    assert not wp.mock_calls
    assert before == (tmp_path / "processed.db").read_bytes()


def test_failed_fact_check_prevents_all_wordpress_writes(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source], [], 0))
    approved.all_claims_supported = False
    approved.issues = ["Interim score incorrectly presented as a final result"]
    wp = Mock()
    store = DedupeStore(tmp_path / "processed.db")
    report = run_pipeline(
        cfg, settings, store, fake_editor(article, approved), wp, report_dir=tmp_path
    )
    assert report["held"] == 1 and report["published"] == 0
    assert not wp.mock_calls
    assert not store.is_published(source.key, source.url)


def test_no_image_does_not_crash_publication(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source], [], 0))
    monkeypatch.setattr("rss_to_wp.pipeline.find_rss_image", lambda *a, **k: None)
    store = DedupeStore(tmp_path / "processed.db")
    wp = Mock()
    wp.find_post_by_source.return_value = None
    wp.get_or_create_category.return_value = 7
    wp._slugify.return_value = "theater-announces-performances"
    wp.create_post.return_value = {"id": 77, "link": "https://example.org/new", "status": "publish"}
    report = run_pipeline(
        cfg, settings, store, fake_editor(article, approved), wp, report_dir=tmp_path
    )
    assert report["published"] == 1 and report["errors"] == 0
    assert store.is_published(source.key, source.url)
    assert wp.create_post.call_args.kwargs["featured_media_id"] is None


def test_remote_duplicate_checked_before_image_upload(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source], [], 0))
    wp = Mock()
    wp.find_post_by_source.return_value = {"id": 77, "link": "https://example.org/old"}
    report = run_pipeline(
        cfg,
        settings,
        DedupeStore(tmp_path / "processed.db"),
        fake_editor(article, approved),
        wp,
        report_dir=tmp_path,
    )
    assert report["duplicates"] == 1
    wp.upload_media.assert_not_called()
    wp.create_post.assert_not_called()


def test_duplicates_do_not_exhaust_candidate_budget(cfg, settings, tmp_path, monkeypatch):
    cfg.feeds[0].max_candidates = 1
    entries = [
        feedparser.FeedParserDict(
            id=f"id{i}",
            title="A meaningful local event",
            summary=TEXT,
            link=f"https://example.org/{i}",
            published=pendulum.now("UTC").subtract(minutes=i).isoformat(),
        )
        for i in range(5)
    ]
    monkeypatch.setattr(
        "rss_to_wp.pipeline.parse_feed", lambda url: feedparser.FeedParserDict(entries=entries)
    )
    store = DedupeStore(tmp_path / "processed.db")
    for i in range(4):
        entries[i]["summary"] = TEXT + f" Earlier story {i}."
        store.mark_processed(
            f"id:id{i}",
            cfg.feeds[0].url,
            "old",
            entries[i]["link"],
            i + 1,
            "https://example.org/old",
        )
    sources, _, _ = collect_sources(cfg, settings, store, 72)
    assert [s.url for s in sources] == ["https://example.org/4"]


def test_duplicate_check_network_failure_is_not_permission_to_publish():
    wp = WordPressClient("https://example.org", "test", "test")
    wp._rate_limit = Mock()
    wp.session = Mock()
    wp.session.get.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout):
        wp.create_post("headline", "body", source_url="https://example.org/source")
    wp.session.post.assert_not_called()


def test_duplicate_source_html_entities_are_decoded():
    wp = WordPressClient("https://example.org", "test", "test")
    wp._rate_limit = Mock()
    wp.session = Mock()
    response = wp.session.get.return_value
    response.headers = {"X-WP-TotalPages": "1"}
    response.json.return_value = [
        {
            "id": 5,
            "content": {"raw": '<a href="https://example.org/story?id=1&amp;part=2">Source</a>'},
        }
    ]
    assert wp.find_post_by_source("https://example.org/story?part=2&id=1")["id"] == 5


def test_truncated_model_response_is_rejected():
    editor = OpenAIRewriter("test")
    editor.client = Mock()
    editor.client.chat.completions.create.return_value.choices = [Mock(finish_reason="length")]
    with pytest.raises(ValueError):
        editor.plan([])


def test_replay_cannot_publish():
    result = CliRunner().invoke(app, ["run", "--replay"])
    assert result.exit_code != 0
    # Rich adds ANSI styling between option names on Linux CI terminals.
    from click import unstyle

    assert "--replay requires --dry-run" in unstyle(result.output)


def test_invalid_plan_does_not_discard_valid_combined_story(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    from dataclasses import replace

    other = replace(source, id="s2", key="other", url="https://example.org/other")
    article.source_ids = ["s1", "s2"]
    editor = fake_editor(article, approved)
    editor.plan.return_value = StoryPlan.model_validate(
        {
            "groups": [
                {"source_ids": ["unknown"], "reason": "bad group"},
                {"source_ids": ["s1", "s2"], "reason": "same event"},
            ]
        }
    )
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source, other], [], 0))
    report = run_pipeline(
        cfg, settings, DedupeStore(tmp_path / "db"), editor, dry_run=True, report_dir=tmp_path
    )
    assert report["eligible"] == 1 and report["errors"] == 0
    assert len(report["stories"]) == 1
    assert editor.plan.call_count == 2


def test_repaired_brief_must_pass_evidence_and_fact_check(
    tmp_path, cfg, settings, source, article, approved, monkeypatch
):
    draft = article.model_copy(deep=True)
    draft.kind = "article"  # A complete brief was misclassified, below 200 words.
    editor = fake_editor(draft, approved)
    editor.repair.return_value = article
    monkeypatch.setattr("rss_to_wp.pipeline.collect_sources", lambda *a: ([source], [], 0))
    report = run_pipeline(
        cfg, settings, DedupeStore(tmp_path / "db"), editor, dry_run=True, report_dir=tmp_path
    )
    assert report["eligible"] == 1
    editor.repair.assert_called_once()
    editor.verify.assert_called_once()
