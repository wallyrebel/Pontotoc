"""Local-only failure and idempotency checks; no live credentials or requests."""
import copy
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

spec = importlib.util.spec_from_file_location('post5997', Path(__file__).parents[1] / 'scripts/correct_post5997.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def response(data=None, content=b'', status=200, pages=1):
    return Mock(status_code=status, json=Mock(return_value=data), content=content,
                text=content.decode('utf-8', errors='replace'),
                headers={'X-WP-TotalPages': str(pages)})


def before():
    post = copy.deepcopy(job.EXPECTED)
    # Simulated raw text; actual production raw is guarded by hashes only.
    for field in ('title', 'content', 'excerpt'):
        post[field]['raw'] = post[field]['rendered']
    post['content']['block_version'] = 0
    return post


def after(media_id=6000):
    post = before()
    post['title'] = {'raw': job.TITLE, 'rendered': job.TITLE}
    post['content']['raw'] = post['content']['rendered'] = job.BODY
    post['excerpt']['raw'] = job.EXCERPT
    post['excerpt']['rendered'] = '<p>' + job.EXCERPT + '</p>\n'
    post['featured_media'] = media_id
    post['modified'] = '2026-10-10T12:00:00'
    return post


def media(ident=6000):
    return {'id': ident, 'slug': job.MEDIA_SLUG, 'mime_type': 'image/jpeg',
            'media_details': {'width': 2048, 'height': 1536},
            'source_url': job.BASE + '/wp-content/uploads/2026/10/' + job.MEDIA_SLUG + '.jpg',
            'alt_text': job.ALT}


@pytest.fixture(autouse=True)
def local_output(tmp_path, monkeypatch):
    monkeypatch.setattr(job, 'OUT', tmp_path)
    monkeypatch.setattr(job, 'APPLY_AUTHORIZED', True)
    monkeypatch.setattr(job, 'EXPECTED_RAW_SHA256', {k: job.digest(before()[k]['raw'].encode()) for k in ('title', 'content', 'excerpt')})


def prepare_route(post=None, existing=None):
    session = Mock()
    session.get.side_effect = [response(post or before()), response([existing] if existing else [])]
    public = Mock(return_value=response(content=job.image_bytes()))
    return session, public


def test_plan_is_read_only_and_payload_has_only_authorized_fields():
    session, public = prepare_route()
    old, found, plan = job.prepare(job.BASE, session, public)
    assert old['id'] == 5997 and found is None and plan['needs_image_upload']
    assert set(plan['payload']) == {'title', 'content', 'excerpt', 'featured_media'}
    assert '23-6' in plan['payload']['content'] and 'Correction:' in plan['payload']['content']
    assert '28-14' not in plan['payload']['content'] and 'John Doe' not in plan['payload']['content']
    session.post.assert_not_called()
    public.assert_not_called()


def test_authenticated_projection_handles_edit_only_fields():
    post = before()
    assert post['content']['block_version'] == 0
    job.initial(post)
    assert job.projection(post['content']) == job.EXPECTED['content']


def test_raw_only_concurrent_edit_blocks_writes():
    post = before()
    post['content']['raw'] += ' '
    session, public = prepare_route(post)
    with pytest.raises(ValueError, match='Authenticated raw before-state changed: content'):
        job.apply(job.BASE, session, public)
    session.post.assert_not_called()


def test_wrong_site_blocks_all_network_access():
    session, public = prepare_route()
    with pytest.raises(ValueError): job.apply('https://other.example', session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()
    public.assert_not_called()


@pytest.mark.parametrize('field,value', [('id', 5882), ('date', '2026-10-09T08:36:42'),
                                      ('slug', 'different'), ('status', 'draft'),
                                      ('featured_media', 1), ('title', {'raw': 'Other', 'rendered': 'Other'}),
                                      ('content', {'raw': 'Other', 'rendered': 'Other'})])
def test_stale_baseline_blocks_writes(field, value):
    post = before()
    post[field] = value
    session, public = prepare_route(post)
    with pytest.raises(ValueError): job.apply(job.BASE, session, public)
    session.post.assert_not_called()


def test_renamed_existing_identical_image_is_reused():
    existing = media()
    existing['slug'] = 'some-earlier-import'
    session, public = prepare_route(existing=existing)
    _, found, plan = job.prepare(job.BASE, session, public)
    assert found['id'] == 6000 and plan['payload']['featured_media'] == 6000
    assert not plan['needs_image_upload']
    session.post.assert_not_called()


def test_media_inventory_paginates_and_detects_duplicate_bytes():
    session = Mock()
    session.get.side_effect = [response([media()], pages=2), response([media(6001)], pages=2)]
    public = Mock(return_value=response(content=job.image_bytes()))
    with pytest.raises(ValueError, match='Multiple existing copies'):
        job.reconcile_media(session, public)
    assert session.get.call_count == 2
    session.post.assert_not_called()


def test_media_collision_blocks_upload():
    session, public = prepare_route(existing=media())
    public.return_value = response(content=b'different image')
    with pytest.raises(ValueError, match='name collision'): job.apply(job.BASE, session, public)
    session.post.assert_not_called()


def test_foreign_media_origin_never_receives_auth_or_public_fetch():
    existing = media()
    existing['source_url'] = 'https://other.example/picture.jpg'
    session, public = prepare_route(existing=existing)
    with pytest.raises(ValueError, match='media origin'): job.apply(job.BASE, session, public)
    session.post.assert_not_called()
    public.assert_not_called()


def test_already_corrected_verifies_without_any_write(monkeypatch):
    session, public = prepare_route(post=after(), existing=media())
    monkeypatch.setattr(job, 'verify', Mock(return_value={'verified': True}))
    assert job.apply(job.BASE, session, public)['verified']
    session.post.assert_not_called()


def test_existing_alt_conflict_requires_review_without_upload():
    existing = media()
    existing['alt_text'] = 'Earlier description'
    session, public = prepare_route(existing=existing)
    with pytest.raises(ValueError, match='alt text'): job.apply(job.BASE, session, public)
    session.post.assert_not_called()


def test_concurrent_edit_aborts_before_upload():
    session, public = prepare_route()
    changed = before()
    changed['modified'] = '2026-10-11T01:00:00'
    session.get.side_effect = [response(before()), response([]), response(changed)]
    with pytest.raises(ValueError, match='Concurrent'): job.apply(job.BASE, session, public)
    session.post.assert_not_called()


def test_uncertain_upload_is_never_retried():
    session, public = prepare_route()
    session.get.side_effect = [response(before()), response([]), response(before())]
    session.post.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout): job.apply(job.BASE, session, public)
    assert session.post.call_count == 1
    assert session.post.call_args.args[0].endswith('/media')


def test_reused_media_causes_exactly_one_post_update(monkeypatch):
    session, public = prepare_route(existing=media())
    session.get.side_effect = [response(before()), response([media()]), response(before()), response(before())]
    session.post.return_value = response(after())
    monkeypatch.setattr(job, 'verify', Mock(return_value={'verified': True}))
    assert job.apply(job.BASE, session, public)['verified']
    session.post.assert_called_once()
    assert session.post.call_args.args[0].endswith('/posts/5997')
    assert session.post.call_args.kwargs['json'] == job.payload(6000)


def test_uncertain_post_update_is_never_retried():
    session, public = prepare_route(existing=media())
    session.get.side_effect = [response(before()), response([media()]), response(before()), response(before())]
    session.post.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout): job.apply(job.BASE, session, public)
    assert session.post.call_count == 1
    assert session.post.call_args.args[0].endswith('/posts/5997')


def test_missing_alt_readback_blocks_post_update():
    session, public = prepare_route()
    session.get.side_effect = [response(before()), response([]), response(before())]
    missing_alt = media()
    missing_alt['alt_text'] = ''
    session.post.side_effect = [response(media(), status=201), response(missing_alt)]
    with pytest.raises(ValueError, match='alt text verification'): job.apply(job.BASE, session, public)
    assert session.post.call_count == 2
    assert all(not c.args[0].endswith('/posts/5997') for c in session.post.call_args_list)


def test_successful_new_upload_then_post_update(monkeypatch):
    session, public = prepare_route()
    session.get.side_effect = [response(before()), response([]), response(before()), response(before())]
    session.post.side_effect = [response(media(), status=201), response(media()), response(after())]
    monkeypatch.setattr(job, 'verify', Mock(return_value={'verified': True}))
    assert job.apply(job.BASE, session, public)['verified']
    assert [c.args[0].split('/wp/v2/')[1] for c in session.post.call_args_list] == ['media', 'media/6000', 'posts/5997']
    assert session.post.call_args_list[0].kwargs['data'] == job.IMAGE.read_bytes()


def test_verify_preserves_dates_slug_and_unrelated_metadata():
    old, updated = before(), after()
    job.same_metadata(old, updated)
    updated['date_gmt'] = '2026-10-10T15:00:00'
    with pytest.raises(ValueError, match='date_gmt'): job.same_metadata(old, updated)


def test_full_readback_verification():
    updated = after()
    session = Mock()
    session.get.side_effect = [response(updated), response(media())]
    page = job.BODY + job.TITLE + media()['source_url']
    public = Mock(side_effect=[response(content=job.image_bytes()),
                              response(job.projection(updated)), response(content=page.encode())])
    assert job.verify(before(), session, 6000, public)['verified']
    session.post.assert_not_called()


def test_supplied_asset_digest_and_scope():
    assert job.digest(job.IMAGE.read_bytes()) == job.IMAGE_SHA
    workflow = (job.ROOT / '.github/workflows/correct-post5997.yml').read_text()
    assert 'schedule:' not in workflow and 'workflow_dispatch:' not in workflow
    assert 'contents: read' in workflow
    assert "paths: [scripts/correct_post5997.py]" in workflow
    assert 'APPLY_AUTHORIZED = False' in (job.ROOT / 'scripts/correct_post5997.py').read_text()


def test_pending_authorization_blocks_all_requests(monkeypatch):
    monkeypatch.setattr(job, 'APPLY_AUTHORIZED', False)
    session, public = prepare_route()
    with pytest.raises(ValueError, match='authorization is pending'): job.apply(job.BASE, session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()
    public.assert_not_called()
