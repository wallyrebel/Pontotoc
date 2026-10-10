"""Approved one-shot PEPA slug update; managed Action only, no create or configuration writes."""
import json
import os
from pathlib import Path

import requests
import reviewed_publish as rp

REQUEST = 'reviewed/requests/pepa-slug-migration-2026-10-10.json'
ARTICLE = 'reviewed/articles/pepa-password-reminder-2026-10-10.json'
DIGEST = 'c7d375cd0ae702a0c7a7dc3446e3506014ccecbc558dd9bfccde11f887f324df'
NEW_SLUG = 'pepa-password-security-tips'
OLD_SLUG = 'pontotoc-reviewed-8f7432d95ed4486809f126f35492ce5ecc365f86b55098c6c4e1fee8927b01a4'


def fingerprint(record, excluded=()):
    return rp.sha(json.dumps({k: v for k, v in record.items() if k not in excluded}, sort_keys=True).encode())


def preserved(record):
    return fingerprint(record, {'slug', 'link', 'guid', 'modified', 'modified_gmt'})


def migrate(t, a, e):
    # Exhaustive authenticated scan and stable ownership check occur on every attempt.
    posts, media = t.probe()
    post, image = t.preflight(a, posts, media)
    rp.require(post and image and post['id'] == e['post_id'] and image['id'] == e['media_id'],
               'Migration post or media identity differs')
    rp.require(preserved(post) == e['preserved_metadata_sha256'] and
               post.get('guid', {}).get('rendered') == e['guid_rendered'],
               'Migration preservation baseline changed')
    rp.require(post['slug'] in {e['old_slug'], a['public_slug']} and
               post['link'] == (e['old_url'] if post['slug'] == e['old_slug'] else e['new_url']),
               'Migration permalink drifted')
    before_post = fingerprint(post, {'slug', 'link', 'modified', 'modified_gmt'})
    before_image = fingerprint(image)
    t.verify(a, post['id'], image)
    served_sha = t.verify_media(a, image)
    rp.require(served_sha == e['served_image_sha256'], 'Migration served image baseline changed')
    if post['slug'] == e['old_slug']:
        rp.require(post.get('modified_gmt') == e['modified_gmt'], 'Migration modification baseline changed')
        plan = t.slug_plan(a, post)
        rp.require(plan['proposed_url'] == e['new_url'], 'Migration target differs from approval')
        # Final single-record read closes drift between the full scan and the bounded write.
        latest, _ = t.api('GET', 'posts/' + str(post['id']), params={'context': 'edit'})
        rp.require(latest == post, 'Migration post changed during preflight')
        t.api('POST', 'posts/' + str(post['id']), json={'slug': a['public_slug']})
    # Unknown write outcomes are resumed through the same marker/IDs, never another create.
    after_posts, after_media = t.probe()
    after, after_image = t.preflight(a, after_posts, after_media)
    rp.require(after and after_image and after['id'] == e['post_id'] and after_image['id'] == e['media_id'] and
               after['slug'] == a['public_slug'] and after['link'] == e['new_url'],
               'Migration resulting identity or permalink differs')
    rp.require(fingerprint(after, {'slug', 'link', 'modified', 'modified_gmt'}) == before_post and
               fingerprint(after_image) == before_image and preserved(after) == e['preserved_metadata_sha256'],
               'Migration changed preserved post or media metadata')
    receipt = t.verify_slug_redirect(a, after['id'], after_image, e['old_url'], e['new_url'])
    rp.require(t.verify_media(a, after_image) == served_sha, 'Migration served image changed')
    return {**receipt, 'read_only': False, 'article_id': a['article_id'],
            'payload_sha256': a['payload_sha'], 'preserved_metadata_sha256': preserved(after),
            'served_image_sha256': served_sha, 'preserved_metadata_verified': True,
            'mutation': {'post_id': e['post_id'], 'fields': ['slug']},
            'old_url_http_status': 301, 'new_url_http_status': 200}


def main():
    report = {'verified': False}
    try:
        request = json.loads(rp.scoped_path(REQUEST, 'reviewed/requests').read_text())
        rp.fields(request, {'schema_version', 'operation', 'authorization', 'intake_request', 'expected'})
        rp.require(request['schema_version'] == 1 and request['operation'] == 'migrate-pepa-slug' and
                   request['authorization'] == 'Parent approved bounded PEPA SEO slug correction on 2026-10-10',
                   'Migration lacks exact bounded approval')
        a = rp.bind_request(request['intake_request'])
        rp.require(request['intake_request']['article_path'] == ARTICLE and a['payload_sha'] == DIGEST and
                   a['public_slug'] == NEW_SLUG and request['intake_request']['mode'] == 'dry-run',
                   'Migration article differs from approved PEPA package')
        e = request['expected']
        rp.fields(e, {'post_id', 'media_id', 'old_slug', 'old_url', 'new_url', 'modified_gmt',
                      'preserved_metadata_sha256', 'guid_rendered', 'served_image_sha256'})
        rp.require(e['post_id'] == 6010 and e['media_id'] == 6011 and e['old_slug'] == OLD_SLUG and
                   e['old_url'] == rp.BASE + '/pontotoc-news/' + OLD_SLUG + '/' and
                   e['new_url'] == rp.BASE + '/pontotoc-news/' + NEW_SLUG + '/' and
                   e['modified_gmt'] == '2026-10-10T17:00:41' and
                   e['guid_rendered'] == rp.BASE + '/?p=6010' and
                   e['served_image_sha256'] == '50e7376cf918e8c87b052a5cdf23b005c413e9f0a76eb0fa55fa9c9faee92cf4' and
                   e['preserved_metadata_sha256'] == '67fc4ae337f33dfec06090c291b3613042f8d692eb3fcca8011668bf4d27e84c',
                   'Migration scope differs from approved preflight')
        rp.require(os.environ['WORDPRESS_BASE_URL'].rstrip('/') == rp.BASE, 'Unexpected managed WordPress site')
        with requests.Session() as session:
            session.auth = (os.environ['WORDPRESS_USERNAME'], os.environ['WORDPRESS_APP_PASSWORD'])
            report = migrate(rp.Transport(session), a, e)
    except Exception as exc:
        report = {'verified': False, 'error_type': type(exc).__name__}
        if isinstance(exc, rp.Guard):
            report['guard_failure'] = str(exc)
    out = rp.ROOT / 'data/reviewed-audit'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0 if report.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
