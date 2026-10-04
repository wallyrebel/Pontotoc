"""Read-only verification of the completed bounded post 5882 correction."""
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

BASE = 'https://pontotocnews.com'
POST_ID = 5882
SLUG = 'phs-volleyball-seniors-celebrate-with-win-on-senior-night'
LINK = 'https://pontotocnews.com/pontotoc-news/phs-volleyball-seniors-celebrate-with-win-on-senior-night/'
FIXTURES = Path(__file__).resolve().parents[1] / 'tests/fixtures/post5882'
EXPECTED = json.loads((FIXTURES / 'before.json').read_text())
SOURCE = json.loads((FIXTURES / 'source.json').read_text())
NEW_RAW = (FIXTURES / 'after-raw.html').read_text()
NEW_RENDERED = (FIXTURES / 'after-rendered.html').read_text()
OUT = Path('data/post5882-audit')
TIMEOUT = (10, 30)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2) if isinstance(data, dict) else data)


def get_json(get, endpoint, **kwargs):
    r = get(endpoint, timeout=TIMEOUT, allow_redirects=False, **kwargs)
    r.raise_for_status()
    if r.status_code != 200:
        raise ValueError('Unexpected read status')
    return r.json()


def read(session):
    return get_json(session.get, BASE + f'/wp-json/wp/v2/posts/{POST_ID}', params={'context': 'edit'})


def unchanged(before, after):
    # Content and modification timestamps are the only authorized differences.
    # REST links include the newly created revision, so they are generated state.
    for field in before:
        if field not in {'content', 'modified', 'modified_gmt', '_links'}:
            if after.get(field) != before[field]:
                raise ValueError('Unrelated field changed: ' + field)


def validate_post(post, corrected=False):
    unchanged(EXPECTED, post)
    raw = NEW_RAW if corrected else EXPECTED['content']['raw']
    rendered = NEW_RENDERED if corrected else EXPECTED['content']['rendered']
    if post['content']['raw'] != raw or post['content']['rendered'] != rendered:
        raise ValueError('Exact body preconditions failed')
    if post['content'].get('protected') != EXPECTED['content'].get('protected'):
        raise ValueError('Content visibility changed')


def verify_source(public_get):
    r = public_get(SOURCE['feed_url'], timeout=TIMEOUT, allow_redirects=False)
    r.raise_for_status()
    if r.status_code != 200:
        raise ValueError('Unexpected source read status')
    save('source-feed.xml', r.text)
    matches = [i for i in ET.fromstring(r.text).findall('./channel/item')
               if i.findtext('link') == SOURCE['source_url']]
    if len(matches) != 1:
        raise ValueError('Exact source item missing or ambiguous')
    item = matches[0]
    text = html.unescape(re.sub(r'<img\b[^>]*>', '', item.findtext('description'), flags=re.I)).strip()
    if (digest(text) != SOURCE['source_sha256'] or
        item.findtext('pubDate') != SOURCE['source_pubdate'] or
        item.findtext('{http://purl.org/dc/elements/1.1/}creator') != SOURCE['source_creator']):
        raise ValueError('Source preconditions failed')
    save('source-item.json', {child.tag: child.text for child in item})


def verify_public(public_get):
    endpoint = BASE + f'/wp-json/wp/v2/posts/{POST_ID}'
    post = get_json(public_get, endpoint)
    for field in ('id', 'status', 'link', 'slug', 'title', 'excerpt', 'featured_media', 'author', 'categories', 'tags'):
        expected = EXPECTED[field]
        if isinstance(expected, dict):
            expected = {k: v for k, v in expected.items() if k != 'raw'}
        if post[field] != expected:
            raise ValueError('Public metadata verification failed')
    if post['content']['rendered'] != NEW_RENDERED:
        raise ValueError('Public body verification failed')
    save('after-public.json', post)
    page = public_get(LINK, timeout=TIMEOUT, allow_redirects=False)
    page.raise_for_status()
    page_text = page.content.decode('utf-8')
    if page.status_code != 200 or NEW_RENDERED.strip() not in page_text:
        raise ValueError('Public page verification failed')
    save('after-page.html', page_text)


def verify_correction(base, session, public_get=requests.get):
    """Read-back only. The completed one-shot write path has been removed."""
    if base.rstrip('/') != BASE:
        raise ValueError('Unexpected WordPress site')
    after = read(session)
    validate_post(after, corrected=True)
    save('after.json', after)
    verify_public(public_get)
    return {'post_id': POST_ID, 'url': LINK, 'verified': True, 'read_only': True,
            'after_raw_sha256': digest(NEW_RAW), 'after_rendered_sha256': digest(NEW_RENDERED),
            'source_sha256': SOURCE['source_sha256'], 'featured_media': after['featured_media']}


def main():
    try:
        with requests.Session() as s:
            s.auth = (os.environ['WORDPRESS_USERNAME'], os.environ['WORDPRESS_APP_PASSWORD'])
            report = verify_correction(os.environ['WORDPRESS_BASE_URL'], s)
    except Exception as exc:
        # Never emit requests, credentials, response objects, or sensitive error messages.
        report = {'post_id': POST_ID, 'verified': False, 'error_type': type(exc).__name__}
    save('report.json', report)
    print(json.dumps(report))
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
