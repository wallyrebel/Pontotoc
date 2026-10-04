"""The bounded correction must fail closed and never repeat uncertain writes."""
import copy
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

spec = importlib.util.spec_from_file_location('job', Path(__file__).parents[1] / 'scripts/correct_post5882.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def response(data=None, text='', status=200):
    return Mock(status_code=status, text=text, content=text.encode('utf-8'), json=Mock(return_value=data))


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setattr(job, 'OUT', tmp_path)
    after = copy.deepcopy(job.EXPECTED)
    after['content']['raw'] = job.NEW_RAW
    after['content']['rendered'] = job.NEW_RENDERED
    public_post = copy.deepcopy(after)
    for field in public_post.values():
        if isinstance(field, dict): field.pop('raw', None)
    public = Mock(side_effect=[response(public_post), response(text=job.NEW_RENDERED)])
    session = Mock()
    session.get.return_value = response(after)
    return after, session, public


def test_exact_read_only_verification(route):
    after, session, public = route
    assert job.verify_correction(job.BASE, session, public)['verified']
    session.post.assert_not_called()
    assert public.call_count == 2


@pytest.mark.parametrize('field,value', [('id', 2761), ('status', 'draft'), ('title', {'raw': 'Other'}),
                                      ('featured_media', 1), ('content', {'raw': 'Changed', 'rendered': 'Changed'})])
def test_mismatch_fails_without_writes(route, field, value):
    after, session, public = route
    after[field] = value
    with pytest.raises(ValueError): job.verify_correction(job.BASE, session, public)
    session.post.assert_not_called()


def test_wrong_site_blocks_all_requests(route):
    _, session, public = route
    with pytest.raises(ValueError): job.verify_correction('https://example.com', session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()
    public.assert_not_called()


def test_retired_executable_has_no_write_calls():
    source = (Path(__file__).parents[1] / 'scripts/correct_post5882.py').read_text()
    assert '.post(' not in source
    assert not hasattr(job, 'correct')
