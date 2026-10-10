"""Bounded October 10 site-page request; preflight remains GET/OPTIONS only."""
import json
import os
import re

import requests
import reviewed_publish as rp

REQUEST = 'reviewed/requests/site-pages-preflight-2026-10-10.json'
COPY = 'reviewed/site-pages/site-pages-2026-10-10.json'
PLANNED = [
    {'key': 'about', 'title': 'About Pontotoc News', 'slug': 'about'},
    {'key': 'biography', 'title': 'Jon Myers', 'slug': 'jon-myers'},
    {'key': 'editorial', 'title': 'Editorial Standards', 'slug': 'editorial-standards'},
    {'key': 'corrections', 'title': 'Corrections Policy', 'slug': 'corrections-policy'},
]
CAPS = ('edit_pages', 'publish_pages', 'edit_published_pages', 'edit_others_pages',
        'read_private_pages', 'edit_users', 'edit_theme_options')
PATTERNS = {
    'about': r'\babout\b|who.we.are|our.story',
    'biography': r'jon.myers|\bbiograph|our.team|meet.the.editor|\bstaff\b',
    'editorial': r'editorial|journalism.standards|ethics|newsroom.standards',
    'corrections': r'correction|accuracy.policy',
}


def digest(record):
    return rp.sha(json.dumps(record, sort_keys=True).encode())


def raw_record(record):
    # Gravity Forms regenerates markup/nonces in content.rendered. Preserve
    # every stored field, including raw copy and metadata, rather than that view.
    if isinstance(record,dict):
        return {k:raw_record(v) for k,v in record.items() if not (k=='rendered' and 'raw' in record)}
    if isinstance(record,list):return [raw_record(v) for v in record]
    return record


def records_digest(records):
    return digest(raw_record(sorted(records,key=lambda x:x['id'])))


def menu_ids(item):
    values = item.get('menus')
    if isinstance(values, int):
        values = [values] if values else []
    rp.require(isinstance(values, list) and all(isinstance(v, int) and v > 0 for v in values),
               'Incomplete menu ownership evidence')
    return set(values)


class Preflight(rp.Transport):
    def api(self, method, endpoint, **kwargs):
        rp.require(method in {'GET', 'OPTIONS'}, 'Site-page copy review pending; writes prohibited')
        return super().api(method, endpoint, **kwargs)

    def all_status(self, kind):
        rp.require(kind in {'pages', 'menu-items'}, 'Unexpected site-page collection')
        schema, _ = self.api('OPTIONS', kind)
        enums = set()
        for e in schema.get('endpoints', []):
            if 'GET' in e.get('methods', []):
                enums = set(e.get('args', {}).get('status', {}).get('items', {}).get('enum', []))
                break
        rp.require({'publish', 'draft', 'future', 'pending', 'private', 'trash', 'auto-draft'} <= enums,
                   'Cannot prove exhaustive site-page statuses')
        results = {}
        for status in sorted(enums - {'any'}):
            page, total, seen = 1, None, set()
            while True:
                rows, headers = self.api('GET', kind, params={
                    'context': 'edit', 'status': status, 'per_page': 100, 'page': page,
                    'orderby': 'id', 'order': 'asc'})
                rp.require(isinstance(rows, list), 'Invalid site-page duplicate lookup')
                try:
                    pages, count = int(headers['X-WP-TotalPages']), int(headers['X-WP-Total'])
                except (KeyError, ValueError, TypeError):
                    raise rp.Guard('Missing site-page pagination evidence') from None
                rp.require(pages >= 0 and count >= 0 and (total is None or total == count),
                           'Site-page collection changed during scan')
                total = count
                for row in rows:
                    rp.require(isinstance(row.get('id'), int) and row.get('status') == status and
                               row['id'] not in seen and row['id'] not in results,
                               'Incomplete or duplicate site-page record')
                    if kind == 'pages':
                        rp.require(isinstance(row.get('slug'), str) and
                                   isinstance(row.get('title', {}).get('raw'), str) and
                                   isinstance(row.get('content', {}).get('raw'), str),
                                   'Cannot inspect existing raw page')
                    else:
                        if 'menus' not in row:
                            # Core omits this field when get_the_terms returns false.
                            # Prove the item's assignments with a post-filtered term read.
                            terms, term_headers = self.api('GET', 'menus', params={
                                'context': 'edit', 'post': row['id'], 'per_page': 100, '_fields': 'id'})
                            rp.require(isinstance(terms, list) and len(terms) <= 1 and
                                       str(len(terms)) == term_headers.get('X-WP-Total') and
                                       term_headers.get('X-WP-TotalPages') in {'0', '1'} and
                                       all(isinstance(t.get('id'), int) and t['id'] > 0 for t in terms),
                                       'Cannot reconcile missing menu ownership')
                            row['menus'] = terms[0]['id'] if terms else 0
                        menu_ids(row)
                    seen.add(row['id']);results[row['id']] = row
                if page >= pages:
                    break
                page += 1
                rp.require(page <= 100, 'Site-page scan exceeds bounded limit')
            rp.require(len(seen) == total, 'Incomplete site-page pagination')
        return list(results.values())

    def run(self):
        me, _ = self.api('GET', 'users/me', params={'context': 'edit', '_fields': 'id,name,description,link,capabilities'})
        capabilities = {k: me.get('capabilities', {}).get(k) is True for k in CAPS}
        rp.require(all(capabilities.values()), 'Site-page project lacks required capabilities')
        author, _ = self.api('GET', 'posts/6010', params={'_fields': 'author'})
        rp.require(me.get('name') == 'Jon Myers' and author.get('author') == me.get('id'),
                   'Managed account is not the approved Jon Myers author')
        rp.require(isinstance(me.get('description'), str), 'Cannot inspect current author description')
        pages = self.all_status('pages')
        schema, _ = self.api('OPTIONS', 'pages')
        properties = schema.get('schema', {}).get('properties', {}).get('meta', {}).get('properties', {})
        seo = {key: properties.get(key, {}).get('type') == 'string' and not
               properties.get(key, {}).get('readonly', properties.get(key, {}).get('readOnly', False))
               for key in ('_seopress_titles_title', '_seopress_titles_desc')}
        items = self.all_status('menu-items')
        locations, _ = self.api('GET', 'menu-locations')
        primary = locations.get('primary', {}).get('menu')
        rp.require(isinstance(primary, int) and primary > 0, 'No assigned primary menu')
        menu, _ = self.api('GET', 'menus/' + str(primary), params={'context': 'edit'})
        rp.require(menu.get('id') == primary, 'Primary menu identity differs')
        primary_items = [i for i in items if primary in menu_ids(i)]
        published = [i for i in primary_items if i['status'] == 'publish']
        rp.require(published and all(isinstance(i.get('parent'), int) and isinstance(i.get('menu_order'), int)
                                    for i in published), 'Incomplete primary navigation structure')
        candidates = {p['key']: [] for p in PLANNED}
        protected = []
        for p in pages:
            identity = rp.plain(p['title']['raw']) + ' ' + p['slug'].replace('-', ' ')
            headings = ' '.join(rp.plain(h) for h in re.findall(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', p['content']['raw'], re.I | re.S))
            for planned in PLANNED:
                if p['slug'] == planned['slug'] or re.search(PATTERNS[planned['key']], identity + ' ' + headings, re.I):
                    # Private/draft body text is not exported; relevant identity and digest suffice.
                    candidates[planned['key']].append({'id': p['id'], 'status': p['status'],
                        'slug': p['slug'], 'title': rp.plain(p['title']['raw']),
                        'url': p.get('link') if p['status'] == 'publish' else None,
                        'record_sha256': digest(p)})
            if re.search(r'contact|privacy|advertis', identity, re.I):
                protected.append({'id': p['id'], 'status': p['status'], 'slug': p['slug'],
                                  'record_sha256': digest(p)})
        routes = []
        for p in PLANNED:
            target = rp.BASE + '/' + p['slug'] + '/'
            r = self.public_get(target, timeout=rp.TIMEOUT, allow_redirects=False)
            rp.require(r.status_code in {200, 301, 302, 404}, 'Proposed page route unavailable to inspect')
            routes.append({**p, 'proposed_url': target, 'http_status': r.status_code,
                           'unoccupied_route': r.status_code == 404})
        root_links = [{'id': i['id'], 'title': rp.plain(i['title']['raw']), 'url': i['url'],
                       'parent': i['parent'], 'menu_order': i['menu_order']}
                      for i in sorted(published, key=lambda x: (x['menu_order'], x['id'])) if i['parent'] == 0]
        return {'verified_preflight': True, 'read_only': True, 'copy_review': 'parent-approved-exact-copy',
            'writes_available': False, 'account_capabilities': capabilities,
            'seo_meta_writable': seo,
            'all_status_page_count': len(pages), 'all_status_menu_item_count': len(items),
            'record_hash_contract':'raw-edit-v1',
            'all_menu_items_snapshot_sha256': records_digest(items),
            'all_existing_menu_item_ids': sorted(i['id'] for i in items),
            'page_snapshot_sha256': records_digest(pages),
            'existing_page_candidates': candidates, 'protected_pages': protected, 'planned_pages': routes,
            'author': {'id': me['id'], 'matches_jon_myers_and_pepa_author': True, 'description_empty': not me['description'].strip(),
                       'description_sha256': rp.sha(me['description'].encode()), 'archive_url': me.get('link'),
                       'theme_biography_display': 'unverified until reviewed biography is saved'},
            'primary_navigation': {'menu_id': primary, 'menu_sha256': digest(menu),
                'menu_item_count': len(primary_items), 'existing_item_ids': sorted(i['id'] for i in primary_items),
                'item_snapshot_sha256': digest(sorted(primary_items, key=lambda x:x['id'])),
                'locations_sha256': digest(locations), 'existing_root_links': root_links,
                'planned_structure': 'Append About as one top-level item; biography, editorial and corrections as its children',
                'next_menu_order': max(i['menu_order'] for i in published) + 1},
            'ready_for_copy_review': all(not values for values in candidates.values()) and all(r['unoccupied_route'] for r in routes)}


def main():
    report = {'verified': False}
    transport=None
    try:
        request = json.loads(rp.scoped_path(REQUEST, 'reviewed/requests').read_text())
        from site_pages_publish import Publisher, load_copy, COPY_SHA
        package=load_copy()
        common={'schema_version':1,'planned_pages':PLANNED,'copy_review':'parent-approved-exact-copy',
                'copy_path':COPY,'copy_sha256':COPY_SHA}
        operation=request.get('operation')
        if operation=='preflight-site-pages':
            rp.require(request==common|{'operation':operation},'Site-page preflight request differs')
        else:
            baseline_path='reviewed/receipts/site-pages-preflight-2026-10-10.json'
            baseline_bytes=rp.scoped_path(baseline_path,'reviewed/receipts').read_bytes()
            rp.require(operation in {'publish-site-pages','verify-site-pages'} and request==common|{
                'operation':operation,'baseline_path':baseline_path,'baseline_sha256':rp.sha(baseline_bytes),
                'publication_authorization':'jon-approved-exact-copy-publication'},'Site-page request exceeds exact approved package')
            baseline=json.loads(baseline_bytes)
        rp.require(os.environ['WORDPRESS_BASE_URL'].rstrip('/') == rp.BASE, 'Unexpected managed WordPress site')
        with requests.Session() as session:
            session.auth = (os.environ['WORDPRESS_USERNAME'], os.environ['WORDPRESS_APP_PASSWORD'])
            if operation=='preflight-site-pages':report=Preflight(session).run()
            else:
                transport=Publisher(session,package,baseline)
                report=transport.run(apply=operation=='publish-site-pages')
    except Exception as exc:
        report = {'verified':False,'error_type':type(exc).__name__}
        if isinstance(exc,rp.Guard):
            report['guard_failure'] = str(exc)
        if transport is not None and hasattr(transport,'safe_diagnostics'):
            report['diagnostics']=transport.safe_diagnostics
    out = rp.ROOT / 'data/reviewed-audit';out.mkdir(parents=True,exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    return 0 if report.get('verified_preflight') or report.get('verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
