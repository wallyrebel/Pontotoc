"""Evidence-backed editorial decisions and deterministic publication gates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

from rss_to_wp.config import EditorialPolicy, FeedConfig


def plain_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def word_count(value: str) -> int:
    return len(re.findall(r"\b\w+(?:['’-]\w+)*\b", plain_text(value)))


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def canonical_url(value: str) -> str:
    """Remove tracking only; preserve identifiers such as Facebook story_fbid."""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Source must have a public HTTP(S) URL")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


@dataclass
class Source:
    id: str
    key: str
    url: str
    title: str
    text: str
    published: str
    feed: FeedConfig
    entry: dict

    def payload(self) -> dict:
        return {
            "id": self.id,
            "publisher": self.feed.source_name or self.feed.name,
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "source_published_at": self.published,
        }

    @property
    def evidence_text(self) -> str:
        # Publisher and timestamp are metadata, not proof of event place/date.
        return f"{self.title} {self.text}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(StrictModel):
    answer: str
    source_id: str
    quote: str


class FiveWs(StrictModel):
    who: Evidence
    what: Evidence
    where: Evidence
    when: Evidence
    why: Evidence


class Article(StrictModel):
    decision: Literal["publish", "hold"]
    reason: str
    kind: Literal["article", "brief"]
    headline: str
    excerpt: str
    body: str
    five_ws: FiveWs
    facts: list[Evidence]
    source_ids: list[str]
    local_relevance: str
    brief_justification: str


class Group(StrictModel):
    source_ids: list[str]
    reason: str


class StoryPlan(StrictModel):
    groups: list[Group]


class Verification(StrictModel):
    approved: bool
    all_claims_supported: bool
    five_ws_in_body: bool
    same_event: bool
    locally_relevant: bool
    no_padding: bool
    no_unresolved_conflicts: bool
    issues: list[str]


def unique_source_words(sources: list[Source]) -> int:
    # Repeated social reposts cannot satisfy the combined-source minimum.
    fragments = set()
    for source in sources:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", source.text):
            if sentence.strip():
                fragments.add(normalize(sentence))
    return sum(word_count(s) for s in fragments)


def validate_article(article: Article, sources: list[Source], policy: EditorialPolicy) -> list[str]:
    problems = []
    if article.decision != "publish":
        return ["editorial_hold: " + article.reason]
    source_map = {source.id: source for source in sources}
    if set(article.source_ids) != set(source_map) or len(article.source_ids) != len(source_map):
        problems.append("source_ids_must_match_group")
    if not article.local_relevance.strip():
        problems.append("missing_local_relevance")
    if article.kind == "brief" and not article.brief_justification.strip():
        problems.append("brief_requires_public_utility")
    if not 4 <= word_count(article.headline) <= 24:
        problems.append("invalid_headline")
    if not 12 <= word_count(article.excerpt) <= 65:
        problems.append("invalid_excerpt")
    if (
        plain_text(article.headline) != article.headline
        or plain_text(article.excerpt) != article.excerpt
    ):
        problems.append("headline_and_excerpt_must_be_plain_text")
    body_words = word_count(article.body)
    minimum = policy.min_brief_words if article.kind == "brief" else policy.min_article_words
    if not minimum <= body_words <= policy.max_article_words:
        problems.append(
            f"body_word_count:{body_words}:required:{minimum}-{policy.max_article_words}"
        )
    source_words = unique_source_words(sources)
    if source_words < policy.min_source_words:
        problems.append(f"insufficient_source_words:{source_words}")
    if body_words > source_words * 2 + 30:
        problems.append("excessive_expansion_of_source")
    soup = BeautifulSoup(article.body, "html.parser")
    allowed_tags = {"p", "h2", "h3", "ul", "ol", "li", "strong", "em", "blockquote"}
    if any(tag.name not in allowed_tags or tag.attrs for tag in soup.find_all(True)):
        problems.append("unsafe_or_unexpected_html")
    paragraphs = [plain_text(str(p)) for p in soup.find_all("p") if plain_text(str(p))]
    if len(paragraphs) < 3:
        problems.append("too_few_paragraphs")
    if len(set(map(normalize, paragraphs))) != len(paragraphs):
        problems.append("repeated_paragraphs")
    evidence = list(article.five_ws.__dict__.items()) + [("fact", fact) for fact in article.facts]
    for label, item in evidence:
        source = source_map.get(item.source_id)
        if (
            not item.answer.strip()
            or not item.quote.strip()
            or source is None
            or normalize(item.quote) not in normalize(source.evidence_text)
        ):
            problems.append("unsupported_evidence:" + label)
    if len({normalize(f.answer) for f in article.facts}) < policy.min_facts:
        problems.append("insufficient_distinct_facts")
    return list(dict.fromkeys(problems))


def validate_verification(check: Verification) -> bool:
    return (
        all(
            [
                check.approved,
                check.all_claims_supported,
                check.five_ws_in_body,
                check.same_event,
                check.locally_relevant,
                check.no_padding,
                check.no_unresolved_conflicts,
            ]
        )
        and not check.issues
    )


def story_slug(sources: list[Source]) -> str:
    seed = "|".join(sorted(canonical_url(s.url) for s in sources))
    return "pn-" + hashlib.sha256(seed.encode()).hexdigest()[:24]
