"""Bounded transport for assistant-reviewed public facts; no research or rewriting."""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import io
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from PIL import Image
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://pontotocnews.com"
TIMEOUT = (10, 40)
CHECKS = {"dates", "locality", "identities", "statistics", "source_support",
          "coherent_prose", "no_invented_quotes_or_context", "public_facts_only",
          "no_allegations_or_private_sensitive_material", "image_rights"}
SEO_CHECKS = {"meaningful_headline", "accurate_concise_description", "relevant_accessible_alt",
              "descriptive_slug", "no_keyword_stuffing", "canonical_and_source_links"}


class Guard(ValueError):
    """Fixed safe diagnostic messages only; never propagate server bodies or secrets."""


def require(ok, message):
    if not ok:
        raise Guard(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected), "Invalid contract fields")


def text(value, maximum=4000):
    require(isinstance(value, str) and 0 < len(value.strip()) <= maximum,
            "Missing or excessive reviewed text")
    require(not re.search(r"[\x00-\x08\x0b-\x1f]", value), "Invalid text characters")
    return value


def timestamp(value):
    from datetime import datetime, timezone
    text(value, 40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Guard("Invalid verification timestamp") from None
    require(parsed.tzinfo is not None and parsed <= datetime.now(timezone.utc),
            "Verification timestamp must be past and timezone aware")


def url(value):
    text(value, 2000)
    p = urlsplit(value)
    require(p.scheme == "https" and p.hostname and p.port in {None, 443} and
            not p.username and not p.password and "." in p.hostname and
            not any(c.isspace() for c in value) and
            not p.hostname.endswith((".local", ".internal", ".localhost")), "Invalid public URL")
    try:
        address = ipaddress.ip_address(p.hostname)
    except ValueError:
        address = None
    require(address is None or address.is_global, "Invalid public URL")
    return value


def canonical(value):
    p = urlsplit(html.unescape(value))
    if p.hostname in {"facebook.com", "www.facebook.com", "m.facebook.com"}:
        post = re.search(r"/posts/(\d+)", p.path)
        if post:
            return "https://www.facebook.com/posts/" + post.group(1)
    query = [(k, v) for k, v in parse_qsl(p.query) if not
             (k.lower().startswith("utm_") or k.lower() in {"fbclid", "gclid"})]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"),
                      urlencode(sorted(query)), ""))


def scoped_path(value, directory):
    text(value, 300)
    path = (ROOT / value).resolve()
    require(path.is_relative_to((ROOT / directory).resolve()) and path.is_file(),
            "Path outside reviewed intake directory or missing")
    return path


def load_article(path):
    a = json.loads(path.read_text())
    fields(a, {"schema_version", "event_keys", "title", "excerpt", "locality",
               "sources", "facts", "paragraphs", "image", "review", "submission"})
    require(a["schema_version"] == 1, "Unsupported article schema")
    text(a["title"], 180)
    text(a["excerpt"], 500)
    text(a["locality"], 300)
    require(isinstance(a["event_keys"], list) and 1 <= len(a["event_keys"]) <= 20 and
            len(set(a["event_keys"])) == len(a["event_keys"]) and all(
                isinstance(k, str) and re.fullmatch(r"[a-z0-9][a-z0-9:.-]{10,240}", k)
                for k in a["event_keys"]), "Invalid stable event keys")
    require(isinstance(a["sources"], list) and 1 <= len(a["sources"]) <= 20,
            "Missing public sources")
    sources = {}
    for s in a["sources"]:
        fields(s, {"id", "url", "verification_url", "role", "title", "publisher", "published_at", "verified_at"})
        text(s["id"], 40)
        require(s["id"] not in sources, "Repeated source ID")
        url(s["url"])
        url(s["verification_url"])
        if s["verification_url"] != s["url"]:
            # Saved Facebook feeds are acceptable evidence when the permalink is login gated.
            require(urlsplit(s["url"]).hostname == "www.facebook.com" and
                    s["verification_url"] in {f["url"] for f in
                        yaml.safe_load((ROOT / "feeds.yaml").read_text())["feeds"]},
                    "Alternative source evidence must be a saved Facebook feed")
        text(s["title"], 300)
        text(s["publisher"], 200)
        require(s["role"] in {"event", "background"}, "Invalid source dedupe role")
        # An undated source is explicitly recorded, never assigned an invented date.
        if s["published_at"] is not None:
            timestamp(s["published_at"])
        timestamp(s["verified_at"])
        sources[s["id"]] = s
    require(any(s["role"] == "event" for s in a["sources"]), "At least one event source required")
    require(isinstance(a["facts"], list) and 1 <= len(a["facts"]) <= 100,
            "Missing fact ledger")
    facts = {}
    for f in a["facts"]:
        fields(f, {"id", "statement", "source_ids", "evidence", "date_context",
                   "locality", "identities", "statistics"})
        text(f["id"], 40)
        require(f["id"] not in facts, "Repeated fact ID")
        for key in ("statement", "evidence", "date_context", "locality", "identities", "statistics"):
            text(f[key])
        require(isinstance(f["source_ids"], list) and f["source_ids"] and
                all(s in sources for s in f["source_ids"]), "Fact references unknown source")
        facts[f["id"]] = f
    require(isinstance(a["paragraphs"], list) and 2 <= len(a["paragraphs"]) <= 30,
            "Article needs a coherent lead and reported supporting paragraphs")
    used = set()
    for p in a["paragraphs"]:
        fields(p, {"text", "fact_ids"})
        text(p["text"])
        require(isinstance(p["fact_ids"], list) and p["fact_ids"] and
                all(f in facts for f in p["fact_ids"]), "Unsupported paragraph")
        used.update(p["fact_ids"])
    require(used == set(facts), "Unused or missing ledger facts")
    r = a["review"]
    fields(r, {"reviewer", "reviewed_at", "decision", "checks", "headline_fact_ids", "excerpt_fact_ids"})
    text(r["reviewer"], 100)
    timestamp(r["reviewed_at"])
    require(r["decision"] == "publish" and isinstance(r["checks"], dict) and
            set(r["checks"]) == CHECKS and all(v is True for v in r["checks"].values()),
            "Editorial review incomplete")
    for key in ("headline_fact_ids", "excerpt_fact_ids"):
        require(isinstance(r[key], list) and r[key] and all(f in facts for f in r[key]),
                "Headline or excerpt unsupported")
    submission = a["submission"]
    fields(submission, {"kind", "publish_intent", "reference"})
    require(submission["kind"] in {"assistant_review", "user_submitted"} and
            submission["publish_intent"] is True, "Explicit publication intent required")
    text(submission["reference"], 500)
    image = a["image"]
    fields(image, {"path", "sha256", "alt_text", "credit", "rights", "rights_reference"})
    require(image["rights"] in {"owned", "permission", "public_domain", "licensed"},
            "Authorized image required")
    for key in ("alt_text", "credit", "rights_reference"):
        text(image[key], 1000)
    data = scoped_path(image["path"], "reviewed/assets").read_bytes()
    require(len(data) <= 12_000_000 and sha(data) == image["sha256"], "Image digest or size mismatch")
    with Image.open(io.BytesIO(data)) as im:
        require(im.format in {"JPEG", "PNG"} and im.width >= 400 and im.height >= 250 and
                im.width * im.height <= 40_000_000, "Invalid reviewed image")
        image["mime"] = "image/jpeg" if im.format == "JPEG" else "image/png"
        image["extension"] = "jpg" if im.format == "JPEG" else "png"
        im.verify()
    a["article_id"] = sha("\n".join(sorted(a["event_keys"])).encode())
    # This legacy slug is a collision guard only. New public URLs come from v2 requests.
    a["legacy_slug"] = "pontotoc-reviewed-" + a["article_id"]
    a["public_slug"] = None
    # Content digest binds the immutable reviewed payload to its marker.
    a["payload_sha"] = sha(path.read_bytes())
    a["marker"] = "pontotoc-reviewed:" + a["article_id"] + ":" + a["payload_sha"]
    a["body"] = "\n".join("<p>" + html.escape(p["text"]) + "</p>" for p in a["paragraphs"])
    a["body"] += "\n<p><em>Photo: " + html.escape(image["credit"]) + "</em></p>"
    a["body"] += "\n<p>Sources: " + "; ".join(
        '<a href="' + html.escape(s["url"], quote=True) + '">' + html.escape(s["title"]) + "</a>"
        for s in a["sources"]) + "</p>"
    a["body"] += "\n<!-- " + a["marker"] + " -->"
    a["body"] += "\n" + "\n".join("<!-- pontotoc-event:" + k + " -->" for k in sorted(a["event_keys"]))
    return a


def bind_request(request):
    """Routing/SEO review lives outside the immutable researched article bytes."""
    version = request.get("schema_version")
    expected = {"schema_version", "article_path", "article_sha256", "mode"}
    if version == 2:
        expected |= {"public_slug", "seo_review"}
    fields(request, expected)
    require(version in {1, 2} and request["mode"] in {"dry-run", "publish"}, "Invalid request mode")
    path = scoped_path(request["article_path"], "reviewed/articles")
    require(sha(path.read_bytes()) == request["article_sha256"], "Reviewed article digest mismatch")
    a = load_article(path)
    if version == 2:
        slug = text(request["public_slug"], 80)
        words = slug.split("-")
        require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", slug) and
                not slug.startswith("pontotoc-reviewed-") and not re.search(r"[a-f0-9]{16,}", slug) and
                len([w for w in words if re.search(r"[a-z]", w)]) >= 2 and
                len(set(words)) == len(words), "Public slug must be readable topic words")
        review = request["seo_review"]
        fields(review, {"reviewer", "reviewed_at", "checks"})
        text(review["reviewer"], 100)
        timestamp(review["reviewed_at"])
        require(isinstance(review["checks"], dict) and set(review["checks"]) == SEO_CHECKS and
                all(v is True for v in review["checks"].values()), "SEO review incomplete")
        title = a["title"].strip()
        description = a["excerpt"].strip()
        alt = a["image"]["alt_text"].strip()
        require(20 <= len(title) <= 120 and len(title.split()) >= 3 and title.lower() not in
                {"breaking news update", "latest news update", "untitled news article"},
                "Headline needs a meaningful concise subject")
        require(30 <= len(description) <= 200 and "<" not in description,
                "Description must be concise accurate plain prose")
        require(12 <= len(alt) <= 250 and alt.lower() not in
                {"featured image", "image of a photo", "a photo of the news"} and
                alt.lower() != title.lower() and not re.search(r"https?://|\.(?:jpg|png)$", alt),
                "Featured alt must describe the relevant image")
        for value in (title, description, alt):
            tokens = re.findall(r"[a-z0-9]+", value.lower())
            require(not any(tokens[i:i + 3] == [tokens[i]] * 3 for i in range(len(tokens) - 2)),
                    "Repeated keyword stuffing rejected")
        # Semantic relevance remains the named reviewer's fact-supported judgment.
        a["public_slug"] = slug
        a["seo_reviewed"] = True
    return a


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []
        self.words = []
        self.canonicals = []
        self.descriptions = []
        self.robots = []
        self.title_words = []
        self.headlines = []
        self._head = False
        self._title = False
        self._h1 = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self._head = True
        if tag == "title" and self._head:
            self._title = True
        if tag == "h1":
            self._h1 = []
        if self._head and tag == "link" and "canonical" in attrs.get("rel", "").lower().split():
            self.canonicals.append(attrs.get("href"))
        if self._head and tag == "meta":
            if attrs.get("name", "").lower() == "description":
                self.descriptions.append(attrs.get("content", ""))
            if attrs.get("name", "").lower() == "robots":
                self.robots.append(attrs.get("content", ""))
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "img":
            self.images.append(attrs)

    def handle_data(self, data):
        self.words.append(data)
        if self._title:
            self.title_words.append(data)
        if self._h1 is not None:
            self._h1.append(data)

    def handle_endtag(self, tag):
        if tag == "head":
            self._head = False
        if tag == "title":
            self._title = False
        if tag == "h1" and self._h1 is not None:
            self.headlines.append("".join(self._h1))
            self._h1 = None


def parsed(value):
    result = Links()
    result.feed(value)
    return result


def plain(value):
    return " ".join(" ".join(parsed(value).words).split())


def public_text(value):
    """WordPress texturizes quotes/dashes; preserve words while normalizing typography."""
    return (plain(value).translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
            "–": "-", "—": "-", "…": "..."})).replace("---", "-").replace("--", "-"))


class Transport:
    def __init__(self, session, public_get=requests.get):
        self.session = session
        self.public_get = public_get

    def api(self, method, endpoint, **kwargs):
        response = self.session.request(method, BASE + "/wp-json/wp/v2/" + endpoint,
                                        timeout=TIMEOUT, allow_redirects=False, **kwargs)
        require(response.status_code in {200, 201}, "WordPress REST request failed; reconcile before retry")
        return response.json(), response.headers

    def collection(self, kind):
        schema, _ = self.api("OPTIONS", kind)
        enums = []
        for endpoint in schema.get("endpoints", []):
            methods = endpoint.get("methods", [])
            if "GET" in methods:
                enums = endpoint.get("args", {}).get("status", {}).get("items", {}).get("enum", [])
                break
        # WordPress's attachment controller advertises only these three lookup
        # statuses, whereas the posts controller includes registered post statuses.
        needed = ({"inherit", "private", "trash"} if kind == "media" else
                  {"publish", "future", "draft", "pending", "private", "trash", "auto-draft"})
        require(needed <= set(enums), "Cannot prove all-status lookup support")
        statuses = sorted(set(enums) - {"any"})
        records = {}
        for status in statuses:
            page = 1
            total = None
            seen = set()
            while True:
                values, headers = self.api("GET", kind, params={"context": "edit", "status": status,
                    "per_page": 100, "page": page, "orderby": "id", "order": "asc"})
                require(isinstance(values, list), "Invalid duplicate lookup result")
                try:
                    pages = int(headers["X-WP-TotalPages"])
                    count = int(headers["X-WP-Total"])
                except (KeyError, TypeError, ValueError):
                    raise Guard("Missing duplicate pagination evidence") from None
                require(pages >= 0 and count >= 0 and (total is None or total == count),
                        "Collection changed during duplicate scan")
                total = count
                for value in values:
                    require(isinstance(value.get("id"), int) and value.get("status") == status and
                            isinstance(value.get("slug"), str), "Incomplete duplicate record")
                    if kind == "posts":
                        require(isinstance(value.get("content", {}).get("raw"), str),
                                "Cannot read raw duplicate record")
                    require(value["id"] not in seen, "Duplicate pagination record")
                    seen.add(value["id"])
                    records[value["id"]] = value
                if page >= pages:
                    break
                page += 1
                require(page <= 500, "Duplicate lookup exceeds bounded limit")
            require(len(seen) == total, "Incomplete duplicate pagination")
        return list(records.values())

    def probe(self):
        me, _ = self.api("GET", "users/me", params={"context": "edit"})
        caps = me.get("capabilities", {})
        require(all(caps.get(c) for c in ("publish_posts", "upload_files", "edit_others_posts", "read_private_posts")),
                "Managed account cannot safely inspect all statuses and publish")
        posts, media = self.collection("posts"), self.collection("media")
        return posts, media

    def preflight(self, a, posts, media):
        own = []
        sources = {canonical(s["url"]) for s in a["sources"] if s["role"] == "event"}
        for p in posts:
            raw = p["content"]["raw"]
            if re.search(r"<!-- pontotoc-reviewed:" + re.escape(a["article_id"]) + r":[0-9a-f]{64} -->", raw):
                own.append(p)
                continue
            require(p["slug"] not in {a["public_slug"], a["legacy_slug"]},
                    "Public slug occupied by another post; no overwrite or suffix creation")
            require(not any("pontotoc-event:" + key + " -->" in raw for key in a["event_keys"]),
                    "Event already exists under another article identity")
            require(not sources.intersection(canonical(link) for link in parsed(raw).links),
                    "Source already used by another post; review overlap before publishing")
        require(len(own) <= 1, "Ambiguous post identity")
        post = own[0] if own else None
        if post:
            require(post["status"] in {"draft", "publish"} and
                    post["content"]["raw"] == a["body"] and
                    post.get("title", {}).get("raw") == a["title"] and
                    post.get("excerpt", {}).get("raw") == a["excerpt"] and not post.get("password"),
                    "Existing article changed or is not resumable; no overwrite")
        marker = "pontotoc-reviewed-media:" + a["article_id"] + ":" + a["image"]["sha256"]
        slug = "pontotoc-reviewed-media-" + a["article_id"] + "-" + a["image"]["sha256"]
        matched = [m for m in media if m["slug"].startswith(slug) or marker in
                   m.get("description", {}).get("raw", "") or slug in m.get("source_url", "")]
        require(len(matched) <= 1, "Ambiguous media identity")
        image = matched[0] if matched else None
        if image:
            require(image["slug"] == slug and image["status"] == "inherit" and
                    marker in image.get("description", {}).get("raw", "") and
                    image.get("mime_type") == a["image"]["mime"], "Media identity changed")
            require(not any(p.get("featured_media") == image["id"] and
                            (post is None or p["id"] != post["id"]) for p in posts),
                    "Reviewed media already used by another article")
        if post:
            require(post.get("featured_media") in {0, image["id"] if image else 0},
                    "Unexpected existing featured image")
        return post, image

    def public(self, value):
        url(value)
        r = self.public_get(value, timeout=TIMEOUT, allow_redirects=False)
        require(r.status_code == 200, "Public link unavailable or redirects; review canonical URL")
        require(len(r.content) <= 15_000_000, "Public response exceeds bound")
        return r

    def check_links(self, a):
        for s in a["sources"]:
            response = self.public(s["verification_url"])
            if s["verification_url"] != s["url"]:
                require(s["url"] in html.unescape(response.text),
                        "Reviewed permalink missing from saved source feed")

    def verify_media(self, a, image):
        require(image.get("alt_text") == a["image"]["alt_text"], "Featured alt text mismatch")
        source = image.get("source_url", "")
        require(source.startswith(BASE + "/wp-content/uploads/"), "Unexpected featured image origin")
        data = self.public(source).content
        # WordPress may recompress images. Compare decoded pixels, tolerating only modest JPEG loss.
        with Image.open(io.BytesIO(data)) as served, Image.open(scoped_path(a["image"]["path"], "reviewed/assets")) as original:
            require(served.size == original.size, "Served image dimensions changed")
            from PIL import ImageChops, ImageStat
            difference = ImageStat.Stat(ImageChops.difference(served.convert("RGB"), original.convert("RGB")))
            require(max(difference.mean) <= 6, "Served image differs from reviewed asset")
        return sha(data)

    def run(self, a, apply=False):
        posts, media = self.probe()
        post, image = self.preflight(a, posts, media)
        self.check_links(a)
        result = {"article_id": a["article_id"], "payload_sha256": a["payload_sha"],
                  "read_only": not apply, "post_id": post["id"] if post else None,
                  "media_id": image["id"] if image else None}
        slug_change = bool(post and a["public_slug"] and post["slug"] != a["public_slug"])
        if not apply:
            if image:
                self.verify_media(a, image)
            if post and post["status"] == "publish" and image:
                self.verify(a, post["id"], image)
            plan = self.slug_plan(a, post) if slug_change else None
            return {**result, "verified_preflight": True, "needs_post": post is None,
                    "needs_media": image is None, "requested_public_slug": a["public_slug"],
                    "existing_public_slug": post["slug"] if post else None,
                    "slug_change_required": slug_change,
                    "url": post.get("link") if post else None, "slug_migration_plan": plan}
        require(not slug_change, "Existing public slug differs; reviewed migration required before publication")
        if post is None:
            require(a["public_slug"] is not None and a.get("seo_reviewed"),
                    "New publication requires version-2 readable slug and SEO review")
            post, _ = self.api("POST", "posts", json={"slug": a["public_slug"], "title": a["title"],
                "content": a["body"], "excerpt": a["excerpt"], "status": "draft"})
            # Reconcile a successful create through the same exhaustive lookup before further writes.
            post, image = self.preflight(a, self.collection("posts"), self.collection("media"))
            require(post is not None, "Created draft not found; stop and reconcile")
            require(post["slug"] == a["public_slug"], "WordPress changed requested public slug; stop and reconcile")
        if image is None:
            image_slug = "pontotoc-reviewed-media-" + a["article_id"] + "-" + a["image"]["sha256"]
            data = scoped_path(a["image"]["path"], "reviewed/assets").read_bytes()
            self.api("POST", "media", data={"slug": image_slug,
                "description": "pontotoc-reviewed-media:" + a["article_id"] + ":" + a["image"]["sha256"],
                "alt_text": a["image"]["alt_text"], "caption": a["image"]["credit"]},
                files={"file": (image_slug + "." + a["image"]["extension"], data, a["image"]["mime"])})
            post, image = self.preflight(a, self.collection("posts"), self.collection("media"))
            require(image is not None, "Uploaded media not found; stop and reconcile")
        # Resume missing metadata without changing a published article.
        if image.get("alt_text") != a["image"]["alt_text"]:
            require(post["status"] == "draft", "Published media metadata differs")
            image, _ = self.api("POST", "media/" + str(image["id"]), json={"alt_text": a["image"]["alt_text"]})
        served_sha = self.verify_media(a, image)
        if post["status"] == "draft":
            # Bind exact draft and featured image before making it public.
            self.api("POST", "posts/" + str(post["id"]), json={"featured_media": image["id"]})
            post, image = self.preflight(a, self.collection("posts"), self.collection("media"))
            require(post and post["featured_media"] == image["id"], "Draft image binding failed")
            self.api("POST", "posts/" + str(post["id"]), json={"status": "publish"})
        return {**result, **self.verify(a, post["id"], image), "served_image_sha256": served_sha}

    def verify(self, a, post_id, image):
        post, _ = self.api("GET", "posts/" + str(post_id), params={"context": "edit"})
        self.preflight(a, [post], [image])
        require(post["status"] == "publish" and post["featured_media"] == image["id"],
                "Published post or image mismatch")
        public = self.public(BASE + "/wp-json/wp/v2/posts/" + str(post_id)).json()
        require(public.get("status") == "publish" and public.get("featured_media") == image["id"] and
                public_text(public["title"]["rendered"]) == public_text(a["title"]) and
                public_text(public["content"]["rendered"]) == public_text(a["body"]) and
                public_text(public["excerpt"]["rendered"]) == public_text(a["excerpt"]), "Public REST body mismatch")
        require({s["url"] for s in a["sources"]} <= set(parsed(public["content"]["rendered"]).links),
                "Public source links mismatch")
        link = post["link"]
        require(link.startswith(BASE + "/"), "Unexpected post origin")
        page_response = self.public(link)
        require("noindex" not in page_response.headers.get("X-Robots-Tag", "").lower(),
                "Public article response is marked noindex")
        page = page_response.text
        require(public_text(a["title"]) in public_text(page) and all(public_text(p["text"]) in public_text(page)
                for p in a["paragraphs"]), "Public page body mismatch")
        page_data = parsed(page)
        self.verify_seo(a, post, page_data)
        require({s["url"] for s in a["sources"]} <= set(page_data.links), "Public page links mismatch")
        require(any((im.get("src") == image["source_url"] or
                    image["source_url"] in im.get("srcset", "")) and
                    im.get("alt") == a["image"]["alt_text"] for im in page_data.images),
                "Featured image absent from public page")
        self.verify_media(a, image)
        self.check_links(a)
        return {"verified": True, "post_id": post_id, "media_id": image["id"], "url": link}

    def verify_seo(self, a, post, page):
        link = post["link"]
        require(urlsplit(link).path.rstrip("/").split("/")[-1] == post["slug"],
                "Public permalink does not match stored slug")
        require(page.canonicals == [link], "Missing, conflicting or non-self canonical URL")
        require(len(page.descriptions) == 1 and public_text(page.descriptions[0]) == public_text(a["excerpt"]),
                "Rendered SEO description differs from reviewed excerpt")
        require(public_text(a["title"]) in public_text("".join(page.title_words)) and
                [public_text(h) for h in page.headlines] == [public_text(a["title"])],
                "Public SEO title or main headline mismatch")
        require(not any("noindex" in r.lower() for r in page.robots), "Public article is marked noindex")

    def slug_plan(self, a, post):
        """Read-only proposal. Ordinary publication never applies a slug migration."""
        require(post["status"] == "publish" and post["featured_media"] > 0,
                "Slug migration requires a verified published article")
        old_url = post["link"]
        require(old_url.startswith(BASE + "/") and old_url.endswith("/" + post["slug"] + "/"),
                "Cannot derive bounded slug migration URL")
        new_url = old_url[:-len(post["slug"]) - 1] + a["public_slug"] + "/"
        response = self.public_get(new_url, timeout=TIMEOUT, allow_redirects=False)
        require(response.status_code == 404, "Proposed public route occupied or unavailable to inspect")
        # Hash public metadata to make a later reviewed migration detect unrelated drift.
        preserved = {k: v for k, v in post.items() if k not in
                     {"slug", "link", "guid", "modified", "modified_gmt"}}
        return {"read_only": True, "post_id": post["id"], "media_id": post["featured_media"],
                "old_url": old_url, "proposed_url": new_url, "target_http_status": 404,
                "expected_old_slug": post["slug"], "expected_modified_gmt": post.get("modified_gmt"),
                "preserved_metadata_sha256": sha(json.dumps(preserved, sort_keys=True).encode()),
                "proposed_rest_method": "POST", "proposed_rest_path": "posts/" + str(post["id"]),
                "proposed_rest_payload": {"slug": a["public_slug"]},
                "approval_required_before_url_change": True, "old_slug_redirect_verified": False}

    def verify_slug_redirect(self, a, post_id, image, old_url, new_url):
        """Read-only post-migration check, for an explicitly approved future migration."""
        require(old_url.startswith(BASE + "/") and new_url.startswith(BASE + "/") and old_url != new_url,
                "Invalid bounded redirect check")
        response = self.public_get(old_url, timeout=TIMEOUT, allow_redirects=False)
        require(response.status_code == 301 and response.headers.get("Location") == new_url,
                "Old permalink does not redirect permanently to reviewed URL")
        receipt = self.verify(a, post_id, image)
        require(receipt["url"] == new_url, "Redirect destination differs from verified permalink")
        return {**receipt, "old_url": old_url, "old_slug_redirect_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", help="reviewed/requests JSON bound to a reviewed article digest")
    parser.add_argument("--probe", action="store_true", help="Authenticated read-only all-status capability check")
    parser.add_argument("--validate", action="store_true", help="Offline validation only")
    args = parser.parse_args()
    report = {"verified": False}
    try:
        require(args.probe != bool(args.request), "Choose probe or request")
        a = None
        if args.request:
            request = json.loads(scoped_path(args.request, "reviewed/requests").read_text())
            a = bind_request(request)
        if args.validate:
            require(a is not None, "Offline validation requires request")
            report = {"validated": True, "read_only": True, "article_id": a["article_id"]}
        else:
            require(os.environ["WORDPRESS_BASE_URL"].rstrip("/") == BASE, "Unexpected managed WordPress site")
            with requests.Session() as session:
                session.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
                transport = Transport(session)
                if args.probe:
                    posts, media = transport.probe()
                    report = {"verified_preflight": True, "read_only": True,
                              "all_status_post_count": len(posts), "all_status_media_count": len(media)}
                else:
                    report = transport.run(a, apply=request["mode"] == "publish")
    except Exception as exc:
        report = {"verified": False, "error_type": type(exc).__name__}
        if isinstance(exc, Guard):
            report["guard_failure"] = str(exc)
    out = ROOT / "data/reviewed-audit"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if report.get("verified") or report.get("verified_preflight") or report.get("validated") else 1


if __name__ == "__main__":
    raise SystemExit(main())
