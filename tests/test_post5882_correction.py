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
    before = copy.deepcopy(job.EXPECTED)
    after = copy.deepcopy(before)
    after['content']['raw'] = job.NEW_RAW
    after['content']['rendered'] = job.NEW_RENDERED
    public_post = copy.deepcopy(after)
    for field in public_post.values():
        if isinstance(field, dict):
            field.pop('raw', None)
    source = job.SOURCE
    import xml.etree.ElementTree as ET
    feed = ET.Element('rss')
    item = ET.SubElement(ET.SubElement(feed, 'channel'), 'item')
    for name, value in [('link', source['source_url']), ('pubDate', source['source_pubdate']),
                        ('{http://purl.org/dc/elements/1.1/}creator', source['source_creator']),
                        ('description', source['source_text'])]:
        ET.SubElement(item, name).text = value
    public = Mock(side_effect=[response(text=ET.tostring(feed, encoding='unicode')),
                              response(text=before['content']['rendered']),
                              response(public_post), response(text=job.NEW_RENDERED)])
    session = Mock()
    session.get.side_effect = [response(before), response(after)]
    session.post.return_value = response()
    return before, after, session, public


def test_exact_content_only_write(route):
    before, after, session, public = route
    assert job.correct(job.BASE, session, public)['verified']
    session.post.assert_called_once_with(job.BASE + '/wp-json/wp/v2/posts/5882',
                                        json={'content': job.NEW_RAW}, timeout=job.TIMEOUT,
                                        allow_redirects=False)
    assert public.call_count == 4
    original_source = before['content']['raw'].split('<p><em>Source:', 1)[1]
    assert original_source in job.NEW_RAW
    assert job.NEW_RAW.count('<p><em>Correction (October 4, 2026):') == 1



@pytest.mark.parametrize('field,value', [('id', 2761), ('status', 'draft'), ('title', {'raw': 'Other'}),
                                      ('link', 'https://example.com'), ('featured_media', 1),
                                      ('content', {'raw': 'Changed', 'rendered': 'Changed'}),
                                      ('slug', 'other')])
def test_changed_post_blocks_write(route, field, value):
    before, _, session, public = route
    before[field] = value
    with pytest.raises(ValueError): job.correct(job.BASE, session, public)
    session.post.assert_not_called()


def test_other_site_blocks_all_requests(route):
    _, _, session, public = route
    with pytest.raises(ValueError): job.correct('https://example.com', session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()
    public.assert_not_called()


def test_source_mismatch_blocks_write(route):
    _, _, session, public = route
    public.side_effect = [response(text='<rss><channel/></rss>')]
    with pytest.raises(ValueError): job.correct(job.BASE, session, public)
    session.get.assert_not_called()
    session.post.assert_not_called()


@pytest.mark.parametrize('field,value', [('title', {'raw': 'Changed'}), ('featured_media', 0),
                                      ('status', 'draft'), ('excerpt', {}), ('categories', [7]),
                                      ('content', {'raw': 'Changed', 'rendered': 'Changed'})])
def test_unrelated_readback_change_fails_without_retry(route, field, value):
    _, after, session, public = route
    after[field] = value
    with pytest.raises(ValueError): job.correct(job.BASE, session, public)
    session.post.assert_called_once()


def test_uncertain_write_never_retries(route):
    _, _, session, public = route
    session.post.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout): job.correct(job.BASE, session, public)
    session.post.assert_called_once()
    assert session.get.call_count == 1


def test_stale_page_blocks_write(route):
    _, _, session, public = route
    items = list(public.side_effect)
    items[1] = response(text='Stale or changed page')
    public.side_effect = items
    with pytest.raises(ValueError): job.correct(job.BASE, session, public)
    session.post.assert_not_called()
