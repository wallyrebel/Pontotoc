"""Exercise writes, uncertainty, duplication and public verification without network."""
import copy
import importlib.util
import io
import json
import html
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
            result = {**value, "id": 10, "featured_media": 0,
                      "link": rp.BASE + "/pontotoc-news/" + value["slug"] + "/", "password": ""}
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
        if self.fail_after == kind or (self.fail_after == "publish" and
                                      kwargs.get("json", {}).get("status") == "publish"):
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
        if self.posts and url == self.posts[0]["link"]:
            post = self.posts[0]
            body = '<head><title>' + html.escape(post["title"]["raw"]) + ' - Pontotoc News</title>'
            body += '<link rel="canonical" href="' + post["link"] + '">'
            body += '<meta name="description" content="' + html.escape(post["excerpt"]["raw"], quote=True) + '"></head>'
            body += '<h1>' + post["title"]["raw"] + '</h1>' + post["content"]["raw"]
            if self.public_bad != "image":
                body += '<img src="' + self.media[0]["source_url"] + '" alt="' + html.escape(self.media[0]["alt_text"], quote=True) + '">'
            return self.response(content=body.encode())
        if url.startswith(rp.BASE + "/pontotoc-news/"):
            return self.response(status=404)
        return self.response(content=b"Verified public source")


def setup(package):
    a = rp.bind_request(seo_request(package))
    backend = Backend(package[2])
    return a, backend, rp.Transport(backend, backend.public)


def seo_request(package, slug="reviewed-public-reminder"):
    return {"schema_version": 2, "article_path": "reviewed/articles/example.json",
            "article_sha256": rp.sha(package[1].read_bytes()), "mode": "dry-run", "public_slug": slug,
            "seo_review": {"reviewer": "Test SEO reviewer", "reviewed_at": "2026-10-09T12:00:00Z",
                           "checks": {k: True for k in rp.SEO_CHECKS}}}


def test_success_and_repeat_are_idempotent(package):
    a, b, t = setup(package)
    result = t.run(a, apply=True)
    assert result["verified"] and result["post_id"] == 10 and result["media_id"] == 20
    assert [w[0] for w in b.writes] == ["posts", "media", "posts/10", "posts/10"]
    b.writes.clear()
    assert t.run(a, apply=True)["verified"]
    assert b.writes == []


@pytest.mark.parametrize("stage", ["posts", "media", "posts/10", "publish"])
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
    lambda a: a["sources"][0].update(url="https://127.0.0.1/private"),
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


def test_facebook_numeric_post_identity_ignores_page_and_mobile_aliases():
    assert rp.canonical("https://www.facebook.com/123/posts/456?utm_source=feed") == \
           rp.canonical("https://m.facebook.com/anotherpage/posts/456/")


def test_unknown_supported_status_also_scanned(package):
    a, b, t = setup(package)
    original = b.request
    def with_custom(method, url, **kwargs):
        if method == "OPTIONS" and url.endswith("/posts"):
            schema = original(method, url, **kwargs).json()
            schema["endpoints"][0]["args"]["status"]["items"]["enum"].append("custom-status")
            return b.response(schema)
        return original(method, url, **kwargs)
    b.request = with_custom
    b.posts.append({"id": 99, "status": "custom-status", "slug": "old", "content": {
        "raw": '<a href="https://official.example/reminder">Source</a>'}})
    with pytest.raises(rp.Guard, match="Source already"):
        t.run(a, apply=True)
    assert not b.writes


def test_public_wordpress_typography_is_accepted_but_raw_article_remains_exact(package):
    article, path, data = package
    article["paragraphs"][0]["text"] = "Officials' reminder explains an account's safeguards."
    path.write_text(json.dumps(article))
    a, b, t = setup(package)
    original = b.public
    def texturized(url, **kwargs):
        response = original(url, **kwargs)
        if "wp-json" in url:
            post = response.json()
            post["content"]["rendered"] = post["content"]["rendered"].replace("&#x27;", "&#8217;")
            return b.response(post)
        if b.posts and url == b.posts[0]["link"]:
            return b.response(content=response.content.replace(b"&#x27;", b"&#8217;"))
        return response
    t.public_get = texturized
    assert t.run(a, apply=True)["verified"]
    b.posts[0]["content"]["raw"] = b.posts[0]["content"]["raw"].replace("&#x27;", "’")
    with pytest.raises(rp.Guard, match="Existing article changed"):
        t.run(a, apply=True)


def rename_post(backend, slug):
    backend.posts[0]["slug"] = slug
    backend.posts[0]["link"] = rp.BASE + "/pontotoc-news/" + slug + "/"


def test_readable_slug_separate_from_content_identity(package):
    a = rp.bind_request(seo_request(package, "public-reminder-guidance"))
    b = rp.bind_request(seo_request(package, "pontotoc-reminder-tips"))
    assert a["public_slug"] != b["public_slug"]
    assert a["article_id"] == b["article_id"] and a["marker"] == b["marker"] and a["body"] == b["body"]
    assert a["payload_sha"] == b["payload_sha"]


def test_existing_changed_slug_is_found_and_never_recreated_or_silently_migrated(package):
    a, b, t = setup(package)
    t.run(a, apply=True)
    rename_post(b, "pontotoc-new-readable-name")
    b.writes.clear()
    report = t.run(a, apply=False)
    assert report["post_id"] == 10 and report["slug_change_required"] and not report["needs_post"]
    with pytest.raises(rp.Guard, match="reviewed migration required"):
        t.run(a, apply=True)
    assert not b.writes
    changed = rp.bind_request(seo_request(package, "pontotoc-new-readable-name"))
    assert t.run(changed, apply=True)["post_id"] == 10
    assert not b.writes and len(b.posts) == len(b.media) == 1


def test_legacy_request_resumes_existing_renamed_post_but_cannot_create(package):
    legacy = rp.load_article(package[1])
    backend = Backend(package[2])
    t = rp.Transport(backend, backend.public)
    with pytest.raises(rp.Guard, match="version-2"):
        t.run(legacy, apply=True)
    assert not backend.writes
    t.run(rp.bind_request(seo_request(package)), apply=True)
    rename_post(backend, "another-readable-public-name")
    backend.writes.clear()
    assert t.run(legacy, apply=True)["post_id"] == 10
    assert not backend.writes


@pytest.mark.parametrize("status", STATUSES[:-1])
def test_slug_collision_all_statuses_fails_closed(package, status):
    a, b, t = setup(package)
    b.posts.append({"id": 99, "status": status, "slug": a["public_slug"], "content": {"raw": "Unrelated post"}})
    with pytest.raises(rp.Guard, match="slug occupied"):
        t.run(a, apply=True)
    assert not b.writes


def test_duplicate_internal_marker_across_two_public_slugs_rejected(package):
    a, b, t = setup(package)
    t.run(a, apply=True)
    duplicate = copy.deepcopy(b.posts[0]); duplicate.update(id=99, slug="another-readable-slug")
    b.posts.append(duplicate); b.writes.clear()
    with pytest.raises(rp.Guard, match="Ambiguous post identity"):
        t.run(a, apply=True)
    assert not b.writes


@pytest.mark.parametrize("slug", ["pontotoc-reviewed-" + "a" * 64, "6010", "pepa_pepa_passwords",
                                  "password-password-tips", "News-Update", "x-" + "f" * 64])
def test_invalid_seo_slug_rejected(package, slug):
    with pytest.raises(rp.Guard):
        rp.bind_request(seo_request(package, slug))


@pytest.mark.parametrize("field,value", [("title", "Latest news update"), ("excerpt", "Too short"),
                                       ("title", "password password password news"),
                                       ("alt_text", "Featured image")])
def test_seo_content_checks_reject_poor_fields(package, field, value):
    article, path, _ = package
    if field == "alt_text":
        article["image"][field] = value
    else:
        article[field] = value
    path.write_text(json.dumps(article))
    with pytest.raises(rp.Guard):
        rp.bind_request(seo_request(package))


def test_incomplete_seo_review_rejected(package):
    request = seo_request(package)
    request["seo_review"]["checks"]["accurate_concise_description"] = False
    with pytest.raises(rp.Guard, match="SEO review incomplete"):
        rp.bind_request(request)


@pytest.mark.parametrize("failure", ["canonical", "duplicate_canonical", "description", "title", "h1", "noindex", "alt"])
def test_rendered_seo_checks_fail_closed(package, failure):
    a, b, t = setup(package)
    t.run(a, apply=True)
    original = b.public
    def broken(url, **kwargs):
        response = original(url, **kwargs)
        if url == b.posts[0]["link"]:
            body = response.text
            if failure == "canonical":
                body = body.replace('rel="canonical"', 'rel="other"')
            elif failure == "duplicate_canonical":
                body = body.replace('</head>', '<link rel="canonical" href="https://wrong.example/"></head>')
            elif failure == "description":
                body = body.replace('name="description"', 'name="other"')
            elif failure == "title":
                body = body.replace('<title>', '<title>Wrong title<!--').replace('</title>', '--></title>')
            elif failure == "h1":
                body = body.replace('<h1>', '<h2>').replace('</h1>', '</h2>')
            elif failure == "noindex":
                body = body.replace('</head>', '<meta name="robots" content="noindex"></head>')
            else:
                body = body.replace(' alt="', ' data-alt="')
            return b.response(content=body.encode())
        return response
    t.public_get = broken
    b.writes.clear()
    with pytest.raises(rp.Guard):
        t.run(a, apply=True)
    assert not b.writes


def test_slug_plan_is_read_only_and_minimal(package):
    a, b, t = setup(package)
    t.run(a, apply=True)
    original_marker = b.posts[0]['content']['raw']
    rename_post(b, 'old-human-readable-url')
    b.writes.clear()
    plan = t.run(a, apply=False)['slug_migration_plan']
    assert plan['proposed_rest_path'] == 'posts/10'
    assert plan['proposed_rest_payload'] == {'slug': 'reviewed-public-reminder'}
    assert plan['target_http_status'] == 404 and plan['approval_required_before_url_change']
    assert not plan['old_slug_redirect_verified'] and not b.writes
    assert b.posts[0]['content']['raw'] == original_marker


@pytest.mark.parametrize('status', [200, 301, 403, 500])
def test_slug_plan_fails_closed_when_target_not_free(package, status):
    a, b, t = setup(package)
    t.run(a, apply=True)
    rename_post(b, 'old-human-readable-url')
    b.writes.clear()
    original = t.public_get
    t.public_get = lambda u, **kw: b.response(status=status) if u.endswith('/reviewed-public-reminder/') else original(u, **kw)
    with pytest.raises(rp.Guard, match='Proposed public route'):
        t.run(a, apply=False)
    assert not b.writes


@pytest.mark.parametrize('status,location,success', [
    (301, 'new', True), (302, 'new', False), (404, None, False),
    (301, 'old', False), (301, 'foreign', False)])
def test_post_migration_redirect_verifier(package, status, location, success):
    a, b, t = setup(package)
    t.run(a, apply=True)
    old = b.posts[0]['link']
    rename_post(b, 'new-readable-public-url')
    new = b.posts[0]['link']
    dest = {'new': new, 'old': old, 'foreign': 'https://foreign.example/'}
    original = t.public_get
    def get(u, **kw):
        assert kw['allow_redirects'] is False
        return b.response(status=status, headers={'Location': dest.get(location)}) if u == old else original(u, **kw)
    t.public_get = get
    b.writes.clear()
    if success:
        assert t.verify_slug_redirect(a, 10, b.media[0], old, new)['old_slug_redirect_verified']
    else:
        with pytest.raises(rp.Guard, match='Old permalink'):
            t.verify_slug_redirect(a, 10, b.media[0], old, new)
    assert not b.writes


def test_public_header_noindex_rejected(package):
    a, b, t = setup(package)
    t.run(a, apply=True)
    original = t.public_get
    def get(u, **kw):
        response = original(u, **kw)
        if u == b.posts[0]['link']:
            response.headers['X-Robots-Tag'] = 'noindex'
        return response
    t.public_get = get
    b.writes.clear()
    with pytest.raises(rp.Guard, match='response is marked noindex'):
        t.run(a, apply=True)
    assert not b.writes


@pytest.fixture
def migration(package):
    import sys
    sys.modules['reviewed_publish'] = rp
    spec = importlib.util.spec_from_file_location('pepa_migration', MODULE.with_name('pepa_slug_migration.py'))
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    a, b, t = setup(package)
    t.run(a, apply=True)
    post = b.posts[0]
    post['guid'] = {'rendered': rp.BASE + '/?p=10'}
    post['modified_gmt'] = '2026-10-10T17:00:41'
    old_slug, old_url = post['slug'], post['link']
    new_slug = 'new-readable-public-url'
    a = rp.bind_request(seo_request(package, new_slug))
    expected = {'post_id':10,'media_id':20,'old_slug':old_slug,'old_url':old_url,
                'new_url':rp.BASE+'/pontotoc-news/'+new_slug+'/',
                'modified_gmt':post['modified_gmt'],'preserved_metadata_sha256':migration.preserved(post),
                'guid_rendered':post['guid']['rendered'],'served_image_sha256':rp.sha(package[2])}
    original_request = b.request
    def request(method, u, **kw):
        response = original_request(method, u, **kw)
        if method == 'POST' and kw.get('json') == {'slug':new_slug}:
            rename_post(b,new_slug)
        return response
    b.request = request
    original_public = t.public_get
    t.public_get = lambda u, **kw: b.response(status=301,headers={'Location':expected['new_url']}) if u==old_url and b.posts[0]['slug']==new_slug else original_public(u,**kw)
    b.writes.clear()
    return migration,a,b,t,expected


def test_retired_slug_route_is_read_only_and_repeatable(migration):
    m,a,b,t,e=migration
    rename_post(b,a['public_slug'])
    assert m.verify_retired(t,a,e)['mutation_path_retired']
    assert m.verify_retired(t,a,e)['read_only'] and not b.writes


def test_retired_slug_route_cannot_apply_unfinished_migration(migration):
    m,a,b,t,e=migration
    with pytest.raises(rp.Guard,match='Retired migration requires'):
        m.verify_retired(t,a,e)
    assert not b.writes


@pytest.mark.parametrize('field', ['author','date','guid','content'])
def test_retired_migration_preservation_guards(migration,field):
    m,a,b,t,e=migration
    rename_post(b,a['public_slug'])
    b.posts[0][field] = {'rendered':'Changed','raw':'Changed'} if field in {'guid','content'} else 'Changed'
    with pytest.raises(rp.Guard):
        m.verify_retired(t,a,e)
    assert not b.writes


def test_retired_migration_bad_redirect_has_no_writes(migration):
    m,a,b,t,e=migration
    rename_post(b,a['public_slug'])
    original=t.public_get
    t.public_get=lambda u,**kw:b.response(status=404) if u==e['old_url'] else original(u,**kw)
    with pytest.raises(rp.Guard,match='Old permalink'):
        m.verify_retired(t,a,e)
    assert not b.writes


@pytest.fixture
def readiness_module():
    import sys
    sys.modules['reviewed_publish']=rp
    spec=importlib.util.spec_from_file_location('site_readiness_probe',MODULE.with_name('site_readiness_probe.py'))
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


class ReadinessBackend(Backend):
    def __init__(self, restricted=False):
        super().__init__(b'')
        self.calls=[]
        self.restricted=restricted
    def request(self,method,u,**kw):
        self.calls.append((method,u,kw))
        assert method in {'GET','OPTIONS'} and kw['allow_redirects'] is False
        path=u.split('/wp-json/')[1]
        if path=='wp/v2/users/me':
            if method=='GET':
                assert kw['params']['_fields']=='id,capabilities,description'
                return self.response({'id':3,'capabilities':{'edit_pages':True,'publish_pages':True,'manage_options':not self.restricted},
                                      'description':'PRIVATE_BIO','email':'PRIVATE_EMAIL','application_password':'PRIVATE_SECRET'})
        if method=='OPTIONS':
            if path.startswith('seopress/v1/options/'):
                return self.response({'endpoints':[{'methods':['GET'],'args':[]},{'methods':['POST'],'args':[]}]})
            return self.response({'endpoints':[{'methods':['GET'],'args':{}},
                {'methods':['POST'],'args':{'description':{'default':'PRIVATE_DEFAULT'}}}]})
        if path=='wp/v2/posts/6010':return self.response({'author':3})
        if path=='wp/v2/types/page':return self.response({'capabilities':{'create_posts':'edit_pages','publish_posts':'publish_pages'}})
        if path=='wp/v2/themes':return self.response([{'stylesheet':'colormag','template':'colormag','status':'active','is_block_theme':False}])
        if path=='wp/v2/menu-locations':return self.response({} if not self.restricted else None,status=200 if not self.restricted else 403)
        if path=='wp/v2/plugins':return self.response([{'plugin':'wp-seopress/seopress.php','status':'active','version':'10.2','license_key':'PRIVATE_SECRET'},
                                                     {'plugin':'unrelated/plugin.php','status':'active'}])
        if path=='seopress/v1/options/sitemaps-settings':return self.response({'seopress_xml_sitemap_general_enable':'1','private':'PRIVATE_SETTING',
                                                                          'seopress_xml_sitemap_post_types_list':{'post':{'include':'1'}}},status=403 if self.restricted else 200)
        return self.response([])
    def public(self,u,**kw):
        assert kw['allow_redirects'] is False
        if u.endswith('/news.xml'):
            return self.response(content=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"><url><news:news/></url></urlset>')
        return self.response(status=404)


def test_readiness_probe_read_only_minimized_and_no_credentials(readiness_module):
    b=ReadinessBackend();report=readiness_module.ReadProbe(b,b.public).run()
    serialized=json.dumps(report)
    assert 'PRIVATE_' not in serialized and 'unrelated/plugin' not in serialized
    assert report['own_description_present'] and report['managed_user_matches_pepa_author']
    assert report['public_sitemaps']['/news.xml']['news_entry_count']==1
    assert report['xml_sitemap_enabled'] is True
    assert all(method in {'GET','OPTIONS'} for method,_,_ in b.calls)
    assert not any('/license' in u or (method=='GET' and '/pro-settings' in u) for method,u,_ in b.calls)
    assert report['read_only'] and not report['writes_tested']
    assert report['routes']['/seopress/v1/options/sitemaps-settings']['editable_field_names']==[]


def test_readiness_reports_denied_reads_without_role_assumptions(readiness_module):
    b=ReadinessBackend(restricted=True);report=readiness_module.ReadProbe(b,b.public).run()
    assert report['menu_locations_http_status']==403 and report['menu_locations'] is None
    assert report['sitemap_options_http_status']==403 and report['xml_sitemap_enabled'] is None
    assert not report['account_capabilities']['manage_options']


@pytest.mark.parametrize('method',['POST','PUT','PATCH','DELETE'])
def test_readiness_transport_refuses_writes(readiness_module,method):
    b=ReadinessBackend()
    with pytest.raises(rp.Guard,match='Read-only probe rejects'):
        readiness_module.ReadProbe(b).read('/wp-json/wp/v2/pages',method)
    assert not b.calls


def test_readiness_refuses_redirects_and_oversized_private_responses(readiness_module):
    b=ReadinessBackend()
    b.request=lambda *args,**kw:b.response({'secret':'PRIVATE_SECRET'},status=301)
    status,data=readiness_module.ReadProbe(b).read('/wp-json/wp/v2/users/me')
    assert status==301 and data is None


def test_missing_sitemap_enable_field_is_unverified_not_false(readiness_module):
    b=ReadinessBackend()
    original=b.request
    def request(method,u,**kw):
        if method=='GET' and u.endswith('/options/sitemaps-settings'):
            return b.response({'seopress_xml_sitemap_general':'1'})
        return original(method,u,**kw)
    b.request=request
    assert readiness_module.ReadProbe(b,b.public).run()['xml_sitemap_enabled'] is None


@pytest.fixture
def site_module():
    import sys
    sys.modules['reviewed_publish']=rp
    spec=importlib.util.spec_from_file_location('site_pages_transport',MODULE.with_name('site_pages_transport.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


class SiteBackend(Backend):
    def __init__(self, site):
        super().__init__(b'');self.calls=[];self.bad_kind=None
        self.pages=[{'id':16,'status':'publish','slug':'contact-us','title':{'raw':'Contact Us'},
                     'content':{'raw':'PRIVATE_EXISTING_BODY'},'link':rp.BASE+'/contact-us/'}]
        self.items=[{'id':41,'status':'publish','title':{'raw':'Home'},'menus':[7],'parent':0,
                     'menu_order':1,'url':rp.BASE+'/','type':'custom','object':'custom','object_id':41}]
        self.site=site
    def request(self,method,u,**kw):
        self.calls.append((method,u))
        assert method in {'GET','OPTIONS'}
        kind=u.split('/wp/v2/')[1]
        if kind=='users/me':return self.response({'id':3,'name':'Jon Myers','description':'','link':rp.BASE+'/author/editor/',
                                                  'capabilities':{k:True for k in self.site.CAPS}})
        if kind=='posts/6010':return self.response({'author':3})
        if kind=='menu-locations':return self.response({'primary':{'menu':7}})
        if kind=='menus/7':return self.response({'id':7,'name':'Main Menu','locations':['primary'],'auto_add':False})
        if method=='OPTIONS':return self.response({'endpoints':[{'methods':['GET'],'args':{'status':{'items':{'enum':STATUSES}}}}],
            'schema':{'properties':{'meta':{'properties':{k:{'type':'string'} for k in ['_seopress_titles_title','_seopress_titles_desc']}}}}})
        rows=self.pages if kind=='pages' else self.items
        if self.bad_kind==kind:return self.response([],status=403)
        rows=[r for r in rows if r['status']==kw['params']['status']]
        return self.response(rows,headers={'X-WP-TotalPages':'1' if rows else '0','X-WP-Total':str(len(rows))})
    def public(self,u,**kw):
        assert kw['allow_redirects'] is False
        return self.response(status=404)


def test_site_preflight_complete_all_status_and_no_private_body_export(site_module):
    b=SiteBackend(site_module);r=site_module.Preflight(b,b.public).run()
    assert r['verified_preflight'] and r['read_only'] and r['ready_for_copy_review']
    assert 'PRIVATE_EXISTING_BODY' not in json.dumps(r)
    assert r['protected_pages'][0]['id']==16 and r['primary_navigation']['menu_id']==7
    assert r['author']['description_empty'] and all(r['seo_meta_writable'].values())
    assert all(method in {'GET','OPTIONS'} for method,_ in b.calls)


@pytest.mark.parametrize('status',[s for s in STATUSES if s!='any'])
def test_site_preflight_recognizes_existing_topic_in_every_status(site_module,status):
    b=SiteBackend(site_module)
    b.pages.append({'id':20,'status':status,'slug':'existing-about','title':{'raw':'About Us'},
                    'content':{'raw':'PRIVATE_ABOUT_BODY'},'link':rp.BASE+'/existing-about/'})
    r=site_module.Preflight(b,b.public).run()
    assert not r['ready_for_copy_review'] and r['existing_page_candidates']['about'][0]['id']==20
    assert 'PRIVATE_ABOUT_BODY' not in json.dumps(r)


@pytest.mark.parametrize('kind',['pages','menu-items'])
def test_site_preflight_lookup_denial_stops(site_module,kind):
    b=SiteBackend(site_module);b.bad_kind=kind
    with pytest.raises(rp.Guard):site_module.Preflight(b,b.public).run()


def test_site_preflight_cannot_write(site_module):
    b=SiteBackend(site_module);t=site_module.Preflight(b,b.public)
    with pytest.raises(rp.Guard,match='writes prohibited'):t.api('POST','pages',json={'status':'publish'})
    assert not b.calls


def test_site_preflight_virtual_route_collision_blocks_creation_plan(site_module):
    b=SiteBackend(site_module)
    b.public=lambda *a,**kw:b.response(status=200)
    r=site_module.Preflight(b,b.public).run()
    assert not r['ready_for_copy_review'] and not any(p['unoccupied_route'] for p in r['planned_pages'])
