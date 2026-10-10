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
    # Simulated authenticated fields, never claimed as captured production raw.
    for field in ('title', 'content', 'excerpt'):
        post[field]['raw'] = post[field]['rendered']
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


def prepare_route(post=None, existing=None):
    session = Mock()
    session.get.side_effect = [response(post or before()), response([existing] if existing else [])]
    public = Mock(return_value=response(content=job.image_bytes()))
    return session, public


def test_retired_executable_has_no_write_calls():
    source = (job.ROOT / 'scripts/correct_post5997.py').read_text()
    assert '.post(' not in source
    assert not hasattr(job, 'apply')
    assert '--apply' not in source


def test_completed_correction_plan_is_read_only():
    session, public = prepare_route(post=after(), existing=media())
    _, _, result = job.prepare(job.BASE, session, public)
    assert result['read_only'] and result['already_corrected']
    session.post.assert_not_called()


def test_wrong_site_blocks_reads():
    session, public = prepare_route()
    with pytest.raises(ValueError): job.prepare('https://other.example', session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()


def test_unchanged_metadata_guard():
    updated = after()
    updated['date'] = '2026-10-11T01:00:00'
    with pytest.raises(ValueError): job.same_metadata(before(), updated)


def test_full_readback_verification():
    updated = after()
    session = Mock()
    session.get.side_effect = [response(updated), response(media())]
    page = job.BODY + job.TITLE + media()['source_url']
    public = Mock(side_effect=[response(content=job.image_bytes()),
                              response(job.projection(updated)), response(content=page.encode())])
    assert job.verify(before(), session, 6000, public)['verified']
    session.post.assert_not_called()


def test_retired_workflow_has_no_write_option_or_schedule():
    workflow = (job.ROOT / '.github/workflows/correct-post5997.yml').read_text()
    assert '--apply' not in workflow and 'schedule:' not in workflow
    assert 'inputs.mode' not in workflow
