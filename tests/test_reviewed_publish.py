"""Exercise writes, uncertainty, duplication and public verification without network."""
import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

MODULE = Path(__file__).resolve().parents[1] / "scripts/reviewed_publish.py"
spec = importlib.util.spec_from_file_location("reviewed_publish", MODULE)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

STATUSES = ["publish", "future", "draft", "pending", "private", "trash", "inherit", "auto-draft", "any"]


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "ROOT", tmp_path)
    (tmp_path / "reviewed/assets").mkdir(parents=True)
    (tmp_path / "reviewed/articles").mkdir()
    data = io.BytesIO()
    Image.new("RGB", (800, 450), "navy").save(data, "PNG")
    (tmp_path / "reviewed/assets/image.png").write_bytes(data.getvalue())
    checks = {k: True for k in rp.CHECKS}
    article = {
        "schema_version": 1, "event_keys": ["ms:pontotoc:2026-10-08:public-reminder"],
        "title": "Reviewed public reminder", "excerpt": "Officials shared a public reminder.",
        "locality": "Pontotoc, Mississippi", "sources": [{"id": "s1", "role": "event", "url": "https://official.example/reminder",
            "verification_url": "https://official.example/reminder", "title": "Original reminder", "publisher": "Official source",
            "published_at": "2026-10-08T22:00:00Z", "verified_at": "2026-10-09T12:00:00Z"}],
        "facts": [{"id": "f1", "statement": "Officials shared a public reminder.", "source_ids": ["s1"],
            "evidence": "Source contains the reminder.", "date_context": "October 8, 2026",
            "locality": "Pontotoc, Mississippi", "identities": "Official source", "statistics": "None asserted"}],
        "paragraphs": [{"text": "Officials shared a public reminder.", "fact_ids": ["f1"]},
                       {"text": "The reminder gives public guidance.", "fact_ids": ["f1"]}],
        "image": {"path": "reviewed/assets/image.png", "sha256": rp.sha(data.getvalue()),
            "alt_text": "An original illustration.", "credit": "Pontotoc News", "rights": "owned",
            "rights_reference": "Original code generated graphic."},
        "review": {"reviewer": "Test reviewer", "reviewed_at": "2026-10-09T12:00:00Z", "decision": "publish",
                   "checks": checks, "headline_fact_ids": ["f1"], "excerpt_fact_ids": ["f1"]},
        "submission": {"kind": "assistant_review", "publish_intent": True, "reference": "Authorized editorial queue"}}
    path = tmp_path / "reviewed/articles/example.json"
    path.write_text(json.dumps(article))
    return article, path, data.getvalue()


class Backend:
    def __init__(self, image):
        self.posts = []
        self.media = []
        self.writes = []
        self.fail_after = None
        self.bad_lookup = None
        self.image = image
        self.public_bad = None

    def response(self, value=None, status=200, headers=None, content=None):
        value = copy.deepcopy(value)
        content = content if content is not None else json.dumps(value).encode()
        return SimpleNamespace(status_code=status, headers=headers or {}, content=content,
                               text=content.decode(errors="replace"), json=lambda: value)

    def request(self, method, url, **kwargs):
        kind = url.split("/wp/v2/")[1]
        if kind == "users/me":
            return self.response({"capabilities": {c: True for c in ["publish_posts", "upload_files", "edit_others_posts", "read_private_posts"]}})
        if method == "OPTIONS":
            enums = ["inherit", "private", "trash"] if kind == "media" else STATUSES
            return self.response({"endpoints": [{"methods": ["GET"], "args": {"status": {"items": {"enum": enums}}}}]})
        if method == "GET" and kind in {"posts", "media"}:
            if self.bad_lookup == kind:
                return self.response([], 403)
            rows = [p for p in getattr(self, kind) if p["status"] == kwargs["params"]["status"]]
            return self.response(rows, headers={"X-WP-TotalPages": "1" if rows else "0", "X-WP-Total": str(len(rows))})
        if method == "GET":
            return self.response(next(p for p in self.posts if p["id"] == int(kind.split("/")[1])))
        self.writes.append((kind, copy.deepcopy(kwargs.get("json", kwargs.get("data")))))
        if kind == "posts":
            value = kwargs["json"]
            result = {**value, "id": 10, "featured_media": 0, "link": rp.BASE + "/reviewed/", "password": ""}
            for field in ("title", "content", "excerpt"):
                result[field] = {"raw": value[field], "rendered": value[field]}
            self.posts.append(result)
        elif kind == "media":
            value = kwargs["data"]
            result = {**value, "id": 20, "status": "inherit", "mime_type": "image/png",
                      "source_url": rp.BASE + "/wp-content/uploads/reviewed.png",
                      "description": {"raw": value["description"]}}
            self.media.append(result)
        else:
            rows = self.posts if kind.startswith("posts/") else self.media
            result = next(p for p in rows if p["id"] == int(kind.split("/")[1]))
            result.update(kwargs["json"])
        if self.fail_after == kind:
            self.fail_after = None
            raise requests.Timeout("simulated unknown write outcome")
        return self.response(result, 201 if kind in {"posts", "media"} else 200)

    def public(self, url, **kwargs):
        if "uploads" in url:
            return self.response(content=self.image)
        if "wp-json" in url:
            post = copy.deepcopy(self.posts[0])
            if self.public_bad == "body":
                post["content"]["rendered"] = "Wrong public body"
            return self.response(post)
        if url == rp.BASE + "/reviewed/":
            post = self.posts[0]
            body = post["title"]["raw"] + post["content"]["raw"]
            if self.public_bad != "image":
                body += '<img src="' + self.media[0]["source_url"] + '">'
            return self.response(content=body.encode())
        return self.response(content=b"Verified public source")


def setup(package):
    a = rp.load_article(package[1])
    backend = Backend(package[2])
    return a, backend, rp.Transport(backend, backend.public)


def test_success_and_repeat_are_idempotent(package):
    a, b, t = setup(package)
    result = t.run(a, apply=True)
    assert result["verified"] and result["post_id"] == 10 and result["media_id"] == 20
    assert [w[0] for w in b.writes] == ["posts", "media", "posts/10", "posts/10"]
    b.writes.clear()
    assert t.run(a, apply=True)["verified"]
    assert b.writes == []


@pytest.mark.parametrize("stage", ["posts", "media", "posts/10"])
def test_unknown_write_outcome_resumes_without_recreate(package, stage):
    a, b, t = setup(package)
    b.fail_after = stage
    with pytest.raises(requests.Timeout):
        t.run(a, apply=True)
    assert t.run(a, apply=True)["verified"]
    assert len(b.posts) == 1 and len(b.media) == 1
    assert [w[0] for w in b.writes].count("posts") == 1
    assert [w[0] for w in b.writes].count("media") == 1


def test_dry_run_performs_no_writes(package):
    a, b, t = setup(package)
    assert t.run(a)["verified_preflight"]
    assert not b.writes and not b.posts and not b.media


@pytest.mark.parametrize("kind", ["posts", "media"])
def test_lookup_errors_fail_closed_before_writes(package, kind):
    a, b, t = setup(package)
    b.bad_lookup = kind
    with pytest.raises(rp.Guard):
        t.run(a, apply=True)
    assert not b.writes


@pytest.mark.parametrize("status", STATUSES[:-1])
def test_source_dedupe_covers_all_statuses_and_tracking_aliases(package, status):
    a, b, t = setup(package)
    b.posts.append({"id": 99, "status": status, "slug": "old-article", "content": {
        "raw": '<a href="https://official.example/reminder/?utm_source=other">Source</a>'}})
    with pytest.raises(rp.Guard, match="Source already"):
        t.run(a, apply=True)
    assert not b.writes


def test_event_dedupe_across_source_feeds(package):
    a, b, t = setup(package)
    b.posts.append({"id": 99, "status": "private", "slug": "other", "content": {
        "raw": "<!-- pontotoc-event:" + a["event_keys"][0] + " -->"}})
    with pytest.raises(rp.Guard, match="Event already"):
        t.run(a, apply=True)
    assert not b.writes


@pytest.mark.parametrize("change", ["content", "status", "media"])
def test_changed_or_trashed_article_never_overwritten(package, change):
    a, b, t = setup(package)
    t.run(a, apply=True)
    if change == "content":
        b.posts[0]["content"]["raw"] += " changed"
    elif change == "status":
        b.posts[0]["status"] = "trash"
    else:
        b.posts[0]["featured_media"] = 999
    b.writes.clear()
    with pytest.raises(rp.Guard):
        t.run(a, apply=True)
    assert not b.writes


@pytest.mark.parametrize("failure", ["body", "image"])
def test_public_verification_failure_never_reports_success(package, failure):
    a, b, t = setup(package)
    b.public_bad = failure
    with pytest.raises(rp.Guard, match="Public|Featured"):
        t.run(a, apply=True)
    b.public_bad = None
    b.writes.clear()
    assert t.run(a, apply=True)["verified"]
    assert not b.writes


@pytest.mark.parametrize("mutate", [
    lambda a: a["review"]["checks"].update(dates=False),
    lambda a: a["submission"].update(publish_intent=False),
    lambda a: a["paragraphs"][0].update(fact_ids=["unknown"]),
    lambda a: a["image"].update(rights="copied_from_feed"),
    lambda a: a["image"].update(sha256="wrong"),
    lambda a: a["sources"][0].update(url="http://localhost/private"),
    lambda a: a.update(extra="unreviewed"),
])
def test_incomplete_or_unsafe_contract_rejected(package, mutate):
    article, path, _ = package
    mutate(article)
    path.write_text(json.dumps(article))
    with pytest.raises(rp.Guard):
        rp.load_article(path)


def test_paginated_lookup_is_complete_and_fail_closed(package):
    a, b, t = setup(package)
    original = b.request
    calls = []
    def paginated(method, url, **kwargs):
        if method == "GET" and url.endswith("/posts") and kwargs["params"]["status"] == "publish":
            page = kwargs["params"]["page"]
            calls.append(page)
            row = {"id": page, "status": "publish", "slug": str(page), "content": {"raw": ""}}
            return b.response([row], headers={"X-WP-Total": "2", "X-WP-TotalPages": "2"})
        return original(method, url, **kwargs)
    b.request = paginated
    assert len(t.collection("posts")) == 2
    assert calls == [1, 2]
    b.request = lambda *args, **kwargs: b.response([]) if args[0] == "GET" else original(*args, **kwargs)
    with pytest.raises(rp.Guard, match="pagination"):
        t.collection("posts")


def test_ambiguous_media_blocks_creation(package):
    a, b, t = setup(package)
    slug = "pontotoc-reviewed-media-" + a["article_id"] + "-" + a["image"]["sha256"]
    b.media = [{"id": n, "slug": slug, "status": "inherit", "source_url": ""} for n in (1, 2)]
    with pytest.raises(rp.Guard, match="Ambiguous media"):
        t.run(a, apply=True)
    assert not b.writes


def test_authorized_user_submission_supported(package):
    article, path, _ = package
    article["submission"] = {"kind": "user_submitted", "publish_intent": True,
                             "reference": "Jon explicitly requested publication in thread"}
    path.write_text(json.dumps(article))
    assert rp.load_article(path)["submission"]["kind"] == "user_submitted"
