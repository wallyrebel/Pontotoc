"""Read-only pre-correction snapshot of exactly Pontotoc post 5882."""
import hashlib
import json
import os
from pathlib import Path

import requests

BASE = "https://pontotocnews.com"
POST_ID = 5882
SLUG = "phs-volleyball-seniors-celebrate-with-win-on-senior-night"
LINK = 'https://pontotocnews.com/pontotoc-news/phs-volleyball-seniors-celebrate-with-win-on-senior-night/'
RENDERED_SHA = "d3da08410e652350cf5b352a0066b2b5c7526746bc93258d86683139513a9b99"
OUT = Path("data/post5882-audit")


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read(session):
    r = session.get(BASE + f"/wp-json/wp/v2/posts/{POST_ID}",
                    params={"context": "edit"}, timeout=(10, 30), allow_redirects=False)
    r.raise_for_status()
    if r.status_code != 200:
        raise ValueError("Unexpected read status")
    return r.json()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        if os.environ["WORDPRESS_BASE_URL"].rstrip("/") != BASE:
            raise ValueError("Unexpected site")
        with requests.Session() as s:
            s.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
            post = read(s)
        if (post["id"] != POST_ID or post["link"] != LINK or
            post["status"] != "publish" or post["slug"] != SLUG or
            post["featured_media"] != 5881 or digest(post["content"]["rendered"]) != RENDERED_SHA):
            raise ValueError("Exact post preconditions failed")
        (OUT / "before.json").write_text(json.dumps(post, indent=2))
        (OUT / "before-raw.html").write_text(post["content"]["raw"])
        (OUT / "before-rendered.html").write_text(post["content"]["rendered"])
        report = {"post_id": POST_ID, "verified": True, "read_only": True,
                  "raw_sha256": digest(post["content"]["raw"]),
                  "rendered_sha256": RENDERED_SHA, "title": post["title"],
                  "featured_media": post["featured_media"]}
    except Exception as exc:
        report = {"post_id": POST_ID, "verified": False, "error_type": type(exc).__name__}
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
