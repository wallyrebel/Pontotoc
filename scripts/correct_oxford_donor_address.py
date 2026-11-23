"""Apply or verify the reviewed address correction to published WordPress post 6496."""
import argparse
import json
import os

import requests

from reviewed_publish import BASE, ROOT, Transport, load_article, require

SLUG = "oxford-blood-donor-center-thanksgiving-hours"
POST = "posts/6496"


def packages():
    before = load_article(ROOT / "reviewed/articles" / (SLUG + "-corrected.json"))
    before.update(public_slug=SLUG, seo_reviewed=True)
    after = load_article(ROOT / "reviewed/articles" / (SLUG + "-hours.json"))
    require(before["article_id"] == after["article_id"] and before["title"] == after["title"]
            and before["excerpt"] == after["excerpt"], "Correction changed article identity")
    after.update(public_slug=SLUG, seo_reviewed=True)
    return before, after


def correct(transport, apply):
    before, after = packages()
    transport.check_links(after)
    def post():
        row, _ = transport.api("GET", POST, params={"context": "edit"})
        require(row["id"] == 6496 and row["slug"] == SLUG and row["status"] == "publish"
                and row["link"] == BASE + "/pontotoc-news/" + SLUG + "/" and not row["password"],
                "Unexpected public article")
        return row

    def before_matches(row):
        original, _ = transport.api("GET", "media/6508", params={"context":"edit"})
        transport.preflight(before, [row], [original])
        require(row["featured_media"] == 6508, "Previous featured image changed")

    current = post()
    image = after["image"]
    slug = "pontotoc-reviewed-media-" + after["article_id"] + "-" + image["sha256"]
    # Reconcile the exact upload before any write, including interrupted attempts.
    def media():
        rows, _ = transport.api("GET", "media", params={"context":"edit", "slug":slug, "status":"inherit"})
        return transport.preflight(after, [], rows)[1]

    attachment = media()
    if current["content"]["raw"] == after["body"]:
        require(attachment is not None, "Missing corrected graphic")
        return transport.verify(after, 6496, attachment)
    before_matches(current)
    if not apply:
        return {"verified_preflight":True, "post_id":6496, "original_media":6508,
                "corrected_asset_sha256":image["sha256"]}
    if attachment is None:
        image_path = ROOT / image["path"]
        try:
            transport.api("POST", "media", data={
                "slug":slug, "alt_text":image["alt_text"], "caption":image["credit"],
                "description":"pontotoc-reviewed-media:" + after["article_id"] + ":" + image["sha256"],
            }, files={"file":(slug + ".png", image_path.read_bytes(), "image/png")})
        except requests.ReadTimeout:
            pass  # WordPress may have finished the upload. Recover only the exact reviewed media.
        attachment = media()
    require(attachment is not None, "Corrected graphic was not found")
    if not attachment.get("alt_text"):
        attachment, _ = transport.api("POST", "media/" + str(attachment["id"]),
                                      json={"alt_text":image["alt_text"]})
    require(attachment.get("alt_text") == image["alt_text"], "Graphic description changed")
    transport.verify_media(after, attachment)
    latest = post()
    before_matches(latest)
    require(latest["modified_gmt"] == current["modified_gmt"], "Post changed during correction")
    transport.api("POST", POST, json={"content":after["body"], "featured_media":attachment["id"]})
    return transport.verify(after, 6496, attachment)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    require(os.environ["WORDPRESS_BASE_URL"].rstrip("/") == BASE, "Unexpected managed site")
    with requests.Session() as session:
        session.auth = (os.environ["WORDPRESS_USERNAME"], os.environ["WORDPRESS_APP_PASSWORD"])
        print(json.dumps(correct(Transport(session), args.apply)))
