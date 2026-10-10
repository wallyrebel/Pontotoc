# Read-only WordPress readiness inspection

`scripts/site_readiness_probe.py` runs inside the existing managed credential
Action when `scripts/reviewed_publish.py --probe` is selected. It supplements the
existing all-status publishing capability check with safe, narrow capability
flags and REST route/read evidence. It permits only GET and OPTIONS, pins the
existing site, and disables redirects. It never tests a write or changes content,
settings, navigation, permissions, plugins, credentials, or assistant schedules.

The report includes relevant account capability booleans, page capability mapping,
self-description presence (not its text), whether the authenticated account is the
PEPA author (not an account snapshot), supported route methods/field names,
field-limited read HTTP statuses, active theme stylesheet/template/block-theme
flag, menu location assignment booleans, and SEOPress plugin status/version only.
Other plugin details, author IDs/contact data/descriptions, page/menu content,
option dumps and schema defaults are excluded from the report.

The dedicated SEOPress XML sitemap settings GET is read, but only the XML-enabled
and post/page inclusion flags are reported. The general PRO settings group and
all license/key endpoints are deliberately unread: the official implementation
returns its whole option group without a registered field-selective read. Its
OPTIONS metadata may be inspected safely. `/robots.txt`, `/sitemaps.xml` and
`/news.xml` are public, unauthenticated, no-redirect checks; XML root/news namespace
and entry counts are reported without exporting the sitemap's article contents.
The `news.xml` route is identified in official SEOPress source.

A schema advertising POST/PUT is not proof that every future write will pass.
Capability flags, authenticated context-edit GETs and WordPress's documented
permission checks establish which operations appear eligible. No write was
attempted. Self-profile updates use the `edit_user` meta capability; WordPress
core permits editing oneself independently of the `edit_users` primitive flag.
Author biography display in the active theme must still be verified if an
approved description is later saved.

Exact managed rerun: GitHub Actions → **Reviewed public facts transport** →
**Run workflow** on main → `operation: probe`. Inspect the `site_readiness` object
in `reviewed-audit-<run_id>/report.json`. Do not copy credentials to the Mac.
Offline tests:

```sh
PYTHONPATH=src python -m pytest -q
```

Readiness inspection is not authorization to create policy commitments, publish
pages, edit a biography, alter menus, configure Google News or install plugins.
Those require a concrete approved next task.

Primary references:
[WordPress profile update permissions](https://developer.wordpress.org/reference/classes/wp_rest_users_controller/update_item_permissions_check/),
[WordPress self-edit capability mapping](https://developer.wordpress.org/reference/functions/map_meta_cap/),
[SEOPress PRO Google News configuration](https://www.seopress.org/support/guides/enable-google-news-xml-sitemap/),
[official SEOPress plugin source](https://wordpress.org/plugins/wp-seopress/).
