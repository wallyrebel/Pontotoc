"""The editorial pipeline keeps insufficient sources eligible for later updates."""

from unittest.mock import Mock

import feedparser
import pendulum
import pytest

from rss_to_wp.config import AppSettings, FeedConfig, FeedsConfig
from rss_to_wp.pipeline import collect_sources, run_pipeline
from rss_to_wp.storage import DedupeStore


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    cfg = FeedsConfig(feeds=[FeedConfig(name="Local", url="https://example.org/feed")])
    settings = AppSettings(
        _env_file=None,
        openai_api_key="test-only",
        wordpress_base_url="https://example.org",
        wordpress_username="test",
        wordpress_app_password="test",
    )
    store = DedupeStore(tmp_path / "processed.db")
    entry = feedparser.FeedParserDict(
        id="same-guid",
        title="Photo",
        link="https://example.org/source",
        published=pendulum.now("UTC").isoformat(),
        summary="",
    )
    monkeypatch.setattr(
        "rss_to_wp.pipeline.parse_feed", lambda _: feedparser.FeedParserDict(entries=[entry])
    )
    return cfg, settings, store, entry, tmp_path


@pytest.mark.parametrize("text", ["", " \n\t", '<img src="photo.jpg">', "Short caption"])
def test_unusable_sources_skip_without_model_or_wp_and_without_consuming_guid(pipeline, text):
    cfg, settings, store, entry, tmp_path = pipeline
    entry["summary"] = text
    editor, wp = Mock(), Mock()
    for _ in range(2):
        report = run_pipeline(cfg, settings, store, editor, wp, report_dir=tmp_path)
        assert report["errors"] == 0 and report["published"] == 0
        assert any(row["outcome"] == "no_usable_text" for row in report["feed_observations"])
    assert not editor.mock_calls and not wp.mock_calls
    assert not store.is_published("id:same-guid", entry.link)


def test_same_guid_and_url_with_later_caption_is_collected(pipeline):
    cfg, settings, store, entry, _ = pipeline
    sources, observations, errors = collect_sources(cfg, settings, store, 72)
    assert not sources and errors == 0
    assert observations[0]["outcome"] == "no_usable_text"
    entry["summary"] = (
        "County officials reopened Main Street after completing bridge repairs today."
    )
    sources, _, errors = collect_sources(cfg, settings, store, 72)
    assert errors == 0
    assert [source.key for source in sources] == ["id:same-guid"]
    assert sources[0].url == entry.link
    assert not store.is_published("id:same-guid", entry.link)


def test_short_meaningful_update_remains_available_for_grouping(pipeline):
    cfg, settings, store, entry, _ = pipeline
    entry["summary"] = "Pontotoc leads the game 14-7 at halftime."
    assert len(entry["summary"]) < 50
    sources, _, errors = collect_sources(cfg, settings, store, 72)
    assert errors == 0 and len(sources) == 1
    # Collection cannot bypass the existing draft and verification gates.
    assert not store.is_published("id:same-guid", entry.link)
