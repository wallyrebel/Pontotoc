"""Bounded correction for post 5997; read-only planning is the default.

No credentials are stored or logged. Run only through the reviewed managed
workflow. Retire apply() and the apply workflow option after verified publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import requests

BASE = 'https://pontotocnews.com'
POST_ID = 5997
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/post5997'
EXPECTED = json.loads((FIXTURES / 'before-public.json').read_text())
BODY = (FIXTURES / 'after-raw.html').read_text()
TITLE = 'Ashley scores twice as Pontotoc beats West Point 23-6 in region opener'
EXCERPT = 'Nolan Ashley ran for two touchdowns and Tim Jones intercepted two passes as Pontotoc beat West Point 23-6 in its Region 1-5A opener.'
ALT = 'A football player in a dark Warriors uniform runs with the ball as two defenders in white and green pursue him.'
IMAGE = ROOT / 'assets/post5997/featured.jpg'
IMAGE_SHA = '069a5e056449afe14df2a0b3e68d96483d47df89cce052a5d925e064c58aef29'
MEDIA_SLUG = 'pontotoc-post5997-' + IMAGE_SHA[:16]
OUT = ROOT / 'data/post5997-audit'
TIMEOUT = (10, 30)
APPLY_AUTHORIZED = False  # Change only after final parent payload/publication approval.
CHANGED = {'title', 'content', 'excerpt', 'featured_media', 'modified', 'modified_gmt', '_links', 'class_list'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def json_request(method, path, **kwargs):
    response = method(BASE + '/wp-json/wp/v2/' + path,
                      timeout=TIMEOUT, allow_redirects=False, **kwargs)
    response.raise_for_status()
    if response.status_code not in {200, 201}:
        raise ValueError('Unexpected REST status')
    return response.json()


def read(session):
    return json_request(session.get, f'posts/{POST_ID}', params={'context': 'edit'})


def projection(value):
    if isinstance(value, dict):
        return {k: projection(v) for k, v in value.items() if k != 'raw'}
    if isinstance(value, list):
        return [projection(v) for v in value]
    return value


def same_metadata(before, after):
    for field, value in before.items():
        if field not in CHANGED and after.get(field) != value:
            raise ValueError('Unrelated field changed: ' + field)


def initial(post):
    # Public fixture pins existing title/body/media, slug, dates and metadata.
    current = projection(post)
    for field, value in EXPECTED.items():
        if field != '_links' and current.get(field) != value:
            raise ValueError('Before-state changed: ' + field)
    if not all(isinstance(post.get(f, {}).get('raw'), str) for f in ('title', 'content', 'excerpt')):
        raise ValueError('Missing authenticated raw content')


def corrected(post, media_id):
    return (post.get('title', {}).get('raw') == TITLE and
            post.get('content', {}).get('raw') == BODY and
            post.get('excerpt', {}).get('raw') == EXCERPT and
            post.get('featured_media') == media_id)


def image_bytes():
    data = IMAGE.read_bytes()
    if digest(data) != IMAGE_SHA:
        raise ValueError('Image digest changed')
    return data


def media_bytes(public_get, media):
    url = media['source_url']
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'pontotocnews.com' or
            not parsed.path.startswith('/wp-content/uploads/') or parsed.query or parsed.fragment):
        raise ValueError('Unexpected media origin')
    # Public byte reads never carry managed credentials.
    response = public_get(url, timeout=TIMEOUT, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError('Unexpected media read status')
    return response.content


def reconcile_media(session, public_get=requests.get):
    """Inspect every JPEG of matching dimensions, including renamed imports.

    Exact-byte reconciliation also finds a prior upload whose response was lost.
    Conflicting deterministic names or multiple exact copies stop the correction.
    """
    matches = []
    page = 1
    while True:
        response = session.get(BASE + '/wp-json/wp/v2/media',
                               params={'context': 'edit', 'media_type': 'image',
                                       'per_page': 100, 'page': page},
                               timeout=TIMEOUT, allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Media listing failed')
        items = response.json()
        pages = int(response.headers['X-WP-TotalPages'])
        if pages > 100:
            raise ValueError('Media inventory exceeds bounded review')
        for item in items:
            details = item.get('media_details', {})
            candidate = (item.get('mime_type') == 'image/jpeg' and
                         details.get('width') == 2048 and details.get('height') == 1536)
            named = item.get('slug', '').startswith(MEDIA_SLUG)
            if candidate or named:
                exact = digest(media_bytes(public_get, item)) == IMAGE_SHA
                if named and not exact:
                    raise ValueError('Correction media name collision')
                if exact:
                    matches.append(item)
        if page >= pages:
            break
        page += 1
    if len(matches) > 1:
        raise ValueError('Multiple existing copies of supplied image')
    return matches[0] if matches else None


def payload(media_id):
    return {'title': TITLE, 'content': BODY, 'excerpt': EXCERPT, 'featured_media': media_id}


def prepare(base, session, public_get=requests.get):
    if base.rstrip('/') != BASE:
        raise ValueError('Unexpected WordPress site')
    image_bytes()
    before = read(session)
    media = reconcile_media(session, public_get)
    media_id = media['id'] if media else None
    same_metadata(EXPECTED, projection(before))
    if not corrected(before, media_id):
        initial(before)
    save('before.json', before)
    save('media-reconciliation.json', {'matching_media': media, 'old_featured_media': before['featured_media']})
    result = {'post_id': POST_ID, 'url': EXPECTED['link'], 'read_only': True,
              'already_corrected': corrected(before, media_id),
              'payload': payload(media_id), 'image_sha256': IMAGE_SHA,
              'image_alt': ALT, 'needs_image_upload': media is None}
    save('plan.json', result)
    return before, media, result


def verify(before, session, media_id, public_get=requests.get):
    after = read(session)
    same_metadata(before, after)
    if not corrected(after, media_id):
        raise ValueError('Exact raw correction verification failed')
    if after['content'].get('protected') != before['content'].get('protected'):
        raise ValueError('Content visibility changed')
    media = json_request(session.get, f'media/{media_id}', params={'context': 'edit'})
    if digest(media_bytes(public_get, media)) != IMAGE_SHA or media['alt_text'] != ALT:
        raise ValueError('Featured image verification failed')
    public = json_request(public_get, f'posts/{POST_ID}')
    for field, expected in projection(after).items():
        if field != '_links' and public.get(field) != expected:
            raise ValueError('Public verification failed: ' + field)
    page = public_get(EXPECTED['link'], timeout=TIMEOUT, allow_redirects=False)
    page.raise_for_status()
    if page.status_code != 200 or after['content']['rendered'].strip() not in page.text:
        raise ValueError('Public page content verification failed')
    if TITLE not in page.text or media['source_url'] not in page.text:
        raise ValueError('Public headline/image verification failed')
    save('after.json', after)
    save('after-public.json', public)
    save('after-page.json', {'html': page.text})
    return {'post_id': POST_ID, 'url': after['link'], 'verified': True,
            'featured_media': media_id, 'image_sha256': IMAGE_SHA}


def apply(base, session, public_get=requests.get):
    if not APPLY_AUTHORIZED:
        raise ValueError('Final payload/publication authorization is pending')
    before, media, plan = prepare(base, session, public_get)
    if plan['already_corrected']:
        return verify(before, session, media['id'], public_get)
    if media and media['alt_text'] != ALT:
        raise ValueError('Existing image alt text needs separate review')
    # Confirm no editor changed the authenticated snapshot during reconciliation.
    if read(session) != before:
        raise ValueError('Concurrent post edit')
    if media is None:
        save('upload-attempt.json', {'image_sha256': IMAGE_SHA, 'slug': MEDIA_SLUG})
        # No automatic POST retry, including timeout/uncertain responses.
        media = json_request(session.post, 'media', data=image_bytes(), headers={
            'Content-Type': 'image/jpeg',
            'Content-Disposition': f'attachment; filename="{MEDIA_SLUG}.jpg"'})
        save('uploaded-media.json', media)
        if media.get('slug') != MEDIA_SLUG or digest(media_bytes(public_get, media)) != IMAGE_SHA:
            raise ValueError('Uploaded image verification failed')
        updated_media = json_request(session.post, f"media/{media['id']}", json={'alt_text': ALT})
        if updated_media.get('alt_text') != ALT:
            raise ValueError('Uploaded image alt text verification failed')
    if read(session) != before:
        raise ValueError('Concurrent post edit after media preparation')
    save('post-write-attempt.json', {'post_id': POST_ID, 'payload': payload(media['id'])})
    json_request(session.post, f'posts/{POST_ID}', json=payload(media['id']))
    return verify(before, session, media['id'], public_get)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.apply and not APPLY_AUTHORIZED:
            raise ValueError('Final payload/publication authorization is pending')
        # Values remain exclusively in the GitHub-managed runner environment.
        with requests.Session() as session:
            session.auth = (os.environ['WORDPRESS_USERNAME'], os.environ['WORDPRESS_APP_PASSWORD'])
            base = os.environ['WORDPRESS_BASE_URL']
            result = apply(base, session) if args.apply else prepare(base, session)[2]
    except Exception as exc:
        result = {'post_id': POST_ID, 'verified': False, 'error_type': type(exc).__name__}
    save('report.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'payload'}))
    return 0 if result.get('read_only') or result.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
