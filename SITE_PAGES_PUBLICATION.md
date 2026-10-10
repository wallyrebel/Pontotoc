# Approved October 10 site pages

Jon approved publication of the exact four-page package in
`reviewed/site-pages/site-pages-2026-10-10.json`, SHA-256
`a9d53b76b05ba1b734eea0774ad581be729757e0bf92d9d4ea8e227708156adc`.
Its `draft_only` flag describes the source drafting artifact; the approved final
WordPress status is `publish`. No future copy is accepted by this one-shot route.

Preflight Action 38081210042 (`c290f724e187d710d5c8d752f45da5b85ce0c9c8`)
proved complete all-status inventories of three pages and 23 menu items, no topic
collisions, four vacant public routes, writable SEOPress title/description fields,
and the managed Jon Myers account (author ID 2). Its minimized receipt is
`reviewed/receipts/site-pages-preflight-2026-10-10.json`. No private page bodies,
credentials, plugin licenses or unrelated settings are included.

The fixed request is `reviewed/requests/site-pages-preflight-2026-10-10.json`.
The existing reviewed workflow invokes `python scripts/reviewed_action.py` and
routes this exact path to `python scripts/site_pages_transport.py`. Existing
GitHub-managed WordPress credentials stay inside the Action environment.
The shared `pontotoc-wordpress-publication` lock serializes publication.

Publication creates exact reviewed drafts carrying a copy-digest ownership
marker, verifies them, then changes only their status to published. A rerun scans
all statuses and resumes owned records instead of recreating them; incomplete
SEO metadata is repaired only on an owned, unchanged draft. Unknown or changed
records stop the run. Existing pages and menu items retain their full record
hashes, including Contact ID 16, Advertise ID 12 and Privacy ID 3. Menu count
changes caused by the four new entries are reconciled without editing settings.

Navigation appends About to the existing primary menu and places Jon Myers,
Editorial Standards and Corrections Policy beneath it. No existing item is
removed or rewritten. Only the authenticated author's own description receives
the approved biography. The route uploads no images and changes no theme,
plugin, sitemap, privacy policy, permissions, credentials or assistant schedules.

Verification checks each public page's exact prose, links, title, H1, canonical,
description and indexability; the rendered primary menu and existing root links;
and the public author description. It reports whether the current theme actually
shows that description on the author archive and the PEPA article. A theme that
omits an author box is reported without changing theme configuration. The
standalone biography page remains linked and public. Contact form delivery is
not tested by submitting a form.

Local regression command (no credentials required):

```sh
.venv/bin/python -m pytest tests/test_reviewed_publish.py -q
```

After verified publication, remove the one-shot mutation implementation, switch
the fixed request to `verify-site-pages`, and deploy a GET/OPTIONS-only verifier.
Record the publication and retirement Actions and receipts here. Article intake,
PEPA article bytes, the retired corrections/slug routes and existing schedules
remain unchanged.

## Verified result and retirement

All four approved pages are live: About 6013, Jon Myers 6014, Editorial Standards
6015 and Corrections Policy 6016. Primary menu ID 2 contains new item IDs
6021–6024; the three policy/biography links are children of About. Contact,
Advertise, Privacy and all 23 original menu items retain stored-field hashes.
Raw content and metadata are protected; regenerated form markup is excluded
from the preservation digest. HTML is decoded as UTF-8 rather than relying on
an HTTP client's Latin-1 default for `text/html` without a charset.

Page creation/publication completed in Action 38081984863 at `48ddd32`; that run
correctly failed verification on the client's HTML decoding. Read-only Action
38082474331 at `997624f` verified pages and stored biography, then detected stale
cached navigation. The final native menu save in Action **38082743595** at
`261fef9` preserved the menu's existing name, description and slug and emitted
WordPress's normal menu completion hook. This invalidated cached navigation
without changing cache, plugin or theme settings. That Action passed public
body, SEO, links, navigation and preservation checks. Its exact minimized
receipt is `reviewed/receipts/site-pages-publication-2026-10-10.json`.

Independent unauthenticated checks and a browser inspection also verified all
four pages and their rendered About submenu on ordinary public URLs. The
approved author description is stored on managed author ID 2 and displays on
the PEPA article. The existing theme omits the biography on the author archive;
the public user REST endpoint returns 404. Both limitations are reported in the
receipt. The standalone biography page is public and linked. No theme or public
user API privacy change was made.

The one-shot `scripts/site_pages_publish.py` is deleted. The fixed request now
uses **`verify-site-pages`**, and `scripts/site_pages_verify.py` permits only
GET/OPTIONS through the read-only transport. The CLI rejects both former
`publish-site-pages` and `finalize-site-navigation` operations. Future copy edits
require a newly reviewed, separately bounded request; this historical route
cannot accept them.

To run a managed read-only verification, dispatch the existing **Reviewed public
facts transport** workflow on `main`, select `operation=request`, and set
`request_path=reviewed/requests/site-pages-preflight-2026-10-10.json`. From an
authorized GitHub CLI environment, the equivalent command is:

```sh
gh workflow run reviewed_publish.yml --repo wallyrebel/Pontotoc --ref main \
  -f operation=request \
  -f request_path=reviewed/requests/site-pages-preflight-2026-10-10.json
```

Inspect the uploaded `reviewed-audit-<run_id>/report.json`; successful retirement
verification requires `verified`, `read_only` and `mutation_path_retired` all
true. No local WordPress credentials are needed or permitted. The existing
article publishing route and assistant schedule remain unchanged.

Primary references for the normal menu save behavior:
[WordPress menu REST update](https://developer.wordpress.org/reference/classes/wp_rest_menus_controller/update_item/)
and [WP Rocket automatic cache clearing](https://docs.wp-rocket.me/article/78-how-often-is-the-cache-updated).

Retirement deployed at `7ad115ac6b8f2b8d248a64ba125e741e722bdc9d`.
Action **38082979352** passed all 127 tests and authenticated/public verification
with `verified: true`, `read_only: true`, `mutation_path_retired: true`. Its exact
receipt is `reviewed/receipts/site-pages-retirement-2026-10-10.json`. The production
route contains no page, author or navigation mutation methods.
