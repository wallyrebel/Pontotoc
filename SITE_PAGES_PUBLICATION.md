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
