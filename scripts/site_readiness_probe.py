"""Read-only WordPress readiness inspection; never export account or option snapshots."""
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import requests
from reviewed_publish import BASE, TIMEOUT, Guard, require

CAPABILITIES = ('edit_pages', 'publish_pages', 'edit_published_pages', 'edit_others_pages',
                'read_private_pages', 'edit_posts', 'edit_users', 'edit_theme_options',
                'manage_options', 'activate_plugins')
ROUTES = ('/wp/v2/pages', '/wp/v2/users/me', '/wp/v2/menus', '/wp/v2/menu-items',
          '/wp/v2/menu-locations', '/wp/v2/navigation', '/wp/v2/themes', '/wp/v2/plugins',
          '/seopress/v1/options/sitemaps-settings', '/seopress/v1/options/pro-settings',
          '/seopress/v1/posts/6010/google-news-settings')


class ReadProbe:
    def __init__(self, session, public_get=requests.get):
        self.session = session
        self.public_get = public_get

    def read(self, path, method='GET', params=None):
        require(method in {'GET', 'OPTIONS'} and path.startswith('/wp-json/') and
                not any(x in path for x in ('..', '?', '#')), 'Read-only probe rejects this request')
        try:
            r = self.session.request(method, BASE + path, params=params,
                                     timeout=TIMEOUT, allow_redirects=False)
            if r.status_code != 200 or len(r.content) > 8_000_000:
                return r.status_code, None
            return r.status_code, r.json()
        except (requests.RequestException, ValueError):
            return None, None

    def public(self, path):
        require(path in {'/robots.txt', '/news.xml', '/sitemaps.xml'}, 'Unexpected public probe path')
        try:
            r = self.public_get(BASE + path, timeout=TIMEOUT, allow_redirects=False)
            report = {'http_status': r.status_code}
            if r.status_code in {301, 302, 307, 308}:
                location = r.headers.get('Location', '')
                p = urlsplit(location)
                # Only same-site paths without query strings are useful public metadata.
                if p.scheme == 'https' and p.netloc == urlsplit(BASE).netloc and not p.query:
                    report['redirect_path'] = p.path
            if r.status_code != 200 or len(r.content) > 8_000_000:
                return report, None
            return report, r.text
        except requests.RequestException:
            return {'http_status': None}, None

    def run(self):
        status, me = self.read('/wp-json/wp/v2/users/me', params={
            'context': 'edit', '_fields': 'id,capabilities,description'})
        require(status == 200 and isinstance(me, dict) and isinstance(me.get('capabilities'), dict),
                'Cannot inspect authenticated capability flags')
        caps = {k: me['capabilities'].get(k) is True for k in CAPABILITIES}
        report = {'read_only': True, 'account_capabilities': caps,
                  'own_description_present': bool(me.get('description', '').strip()),
                  'writes_tested': False, 'license_credentials_requested': False}
        status, article = self.read('/wp-json/wp/v2/posts/6010', params={'_fields': 'author'})
        report['managed_user_matches_pepa_author'] = article.get('author') == me.get('id') if status == 200 and isinstance(article, dict) else None
        routes = {}
        for path in ROUTES:
            status, schema = self.read('/wp-json' + path, method='OPTIONS')
            entry = {'options_http_status': status, 'registered_methods': [], 'editable_field_names': []}
            if status == 200 and isinstance(schema, dict):
                for e in schema.get('endpoints', []):
                    methods = e.get('methods', [])
                    entry['registered_methods'].extend(methods)
                    if set(methods) & {'POST', 'PUT', 'PATCH'}:
                        # Names only: never include defaults or argument values.
                        arguments = e.get('args', {})
                        if isinstance(arguments, dict):
                            entry['editable_field_names'].extend(arguments.keys())
                entry['registered_methods'] = sorted(set(entry['registered_methods']))
                entry['editable_field_names'] = sorted(set(entry['editable_field_names']))
            routes[path] = entry
        report['routes'] = routes
        # Read access is tested with field-limited core endpoints. Schema advertisement
        # and capability flags alone cannot prove a future write will pass every hook.
        for path in ('pages', 'menus', 'menu-items', 'navigation'):
            status, _ = self.read('/wp-json/wp/v2/' + path,
                                  params={'context': 'edit', 'per_page': 1, '_fields': 'id'})
            routes['/wp/v2/' + path]['edit_context_get_http_status'] = status
        status, page_type = self.read('/wp-json/wp/v2/types/page',
                                     params={'context': 'edit', '_fields': 'capabilities'})
        report['page_type_http_status'] = status
        report['page_capability_mapping'] = {
            k: page_type['capabilities'].get(k) for k in ('create_posts', 'publish_posts', 'edit_posts', 'edit_published_posts')
        } if status == 200 and isinstance(page_type, dict) and isinstance(page_type.get('capabilities'), dict) else None
        status, themes = self.read('/wp-json/wp/v2/themes', params={
            'status': 'active', '_fields': 'stylesheet,template,status,is_block_theme'})
        report['active_theme_http_status'] = status
        report['active_themes'] = [{k: t.get(k) for k in ('stylesheet', 'template', 'status', 'is_block_theme')}
                                   for t in themes if t.get('status') == 'active'] if status == 200 and isinstance(themes, list) else []
        status, locations = self.read('/wp-json/wp/v2/menu-locations')
        report['menu_locations_http_status'] = status
        report['menu_locations'] = {k: {'assigned': bool(v.get('menu'))} for k,v in locations.items()
                                    if isinstance(v, dict)} if status == 200 and isinstance(locations, dict) else None
        status, plugins = self.read('/wp-json/wp/v2/plugins', params={'_fields': 'plugin,status,version'})
        report['plugin_metadata_http_status'] = status
        report['seopress_plugins'] = [{k: p.get(k) for k in ('plugin','status','version')}
                                    for p in plugins if 'seopress' in p.get('plugin', '').lower()] if status == 200 and isinstance(plugins, list) else []
        # This dedicated XML sitemap group contains sitemap configuration, not the
        # general PRO/license/API-key group. Only three relevant flags leave memory.
        status, options = self.read('/wp-json/seopress/v1/options/sitemaps-settings')
        report['sitemap_options_http_status'] = status
        if status == 200 and isinstance(options, dict):
            flag = options.get('seopress_xml_sitemap_general_enable')
            report['xml_sitemap_enabled'] = flag in {'1', 1, True} if isinstance(flag, (str, int, bool)) else None
            included = options.get('seopress_xml_sitemap_post_types_list', {})
            report['xml_sitemap_includes'] = {k: isinstance(included, dict) and isinstance(included.get(k), dict) and
                included[k].get('include') in {'1', 1, True} for k in ('post','page')}
        else:
            report['xml_sitemap_enabled'] = None
        # OPTIONS only for PRO settings. Its callback returns the complete option
        # group; a safe, filtered news-only read has not been validated here.
        report['news_configuration_get_skipped'] = 'General PRO option group not requested; safe selective news read remains unverified'
        report['license_status'] = 'unverified; license/key endpoints intentionally not read'
        sitemap_reports = {}
        for path in ('/robots.txt', '/sitemaps.xml', '/news.xml'):
            result, body = self.public(path)
            if path == '/robots.txt' and body:
                result['advertises_same_site_sitemap'] = any(
                    line.strip().lower().startswith('sitemap:') and line.split(':',1)[1].strip().startswith(BASE+'/')
                    for line in body.splitlines())
            elif body and '<!DOCTYPE' not in body.upper():
                try:
                    xml = ET.fromstring(body)
                    result['xml_root'] = xml.tag.rsplit('}',1)[-1]
                    result['news_entry_count'] = len(xml.findall('.//{http://www.google.com/schemas/sitemap-news/0.9}news'))
                    result['has_news_namespace'] = 'http://www.google.com/schemas/sitemap-news/0.9' in body
                except ET.ParseError:
                    result['valid_xml'] = False
            sitemap_reports[path] = result
        report['public_sitemaps'] = sitemap_reports
        return report
