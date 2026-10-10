# PEPA URL migration — completed and write path retired

The original implementation incorrectly exposed the internal article hash as the
public slug. New intake requests now separate a readable URL from the stable
article/event identity. The parent approved this concrete correction. Post 6010 now uses the readable URL; the old URL permanently redirects to it.

## Completed change

- Existing post: **6010**; featured media: **6011**.
- Existing URL: https://pontotocnews.com/pontotoc-news/pontotoc-reviewed-8f7432d95ed4486809f126f35492ce5ecc365f86b55098c6c4e1fee8927b01a4/
- Proposed URL: https://pontotocnews.com/pontotoc-news/pepa-password-security-tips/
- Minimal proposed REST operation: `POST /wp-json/wp/v2/posts/6010` with
  `{"slug":"pepa-password-security-tips"}`.
- Immutable article file SHA-256:
  `c7d375cd0ae702a0c7a7dc3446e3506014ccecbc558dd9bfccde11f887f324df`.
- Internal article ID:
  `8f7432d95ed4486809f126f35492ce5ecc365f86b55098c6c4e1fee8927b01a4`.

The approved article JSON, headline, excerpt, body, immutable markers, image,
source links, publication date and post/media IDs stay intact. No SEO plugin
metadata, credentials, permissions or site configuration changes are proposed.
WordPress may update its modification timestamp and permalink on a slug change.

## Preflight and verified SEO evidence

`reviewed/requests/pepa-slug-preflight-2026-10-10.json` is a version-2 request,
mode **dry-run**, bound to the original article digest. Pushes containing this
request launch the existing managed Action. The transport verifies all-status
post/media identities and collisions, exact authenticated content, public
REST/page content, featured image bytes and alt text, source links, title/H1,
self-canonical URL, description and indexability before proposing the migration.
The target must return 404 without following redirects. The artifact records the
IDs, old/new URL, modification time and preservation fingerprint. Ordinary article
publication cannot rename an existing article. The approved one-shot migration
used a separate fixed request, whose write branch has now been removed.

Read-only inspection of the current page found one self-canonical URL, matching
headline, and a rendered description equal to the approved excerpt. REST exposes
registered SEOPress title, description and canonical fields; their current
values are empty. This establishes the current excerpt fallback only. No plugin
meta write/render behavior has been tested or assumed.

A read-only request to `https://pontotocnews.com/?p=6010` returned 301 to the
current permalink with `X-Redirect-By: WordPress`. That verifies a canonical
ID redirect, **not** an old-slug redirect.

## Executed migration procedure (historical)

1. Wait for the shared `pontotoc-wordpress-publication` lock and any active
   reviewed transport run to finish. Use the existing managed GitHub Action;
   never obtain the WordPress password on the Mac or retry connector writes.
2. Re-run exhaustive preflight. Require post 6010/media 6011, the old slug,
   unchanged content/metadata snapshot and an unoccupied target. If anything
   drifts, stop for review before changing the URL.
3. Implement and test a bounded, explicit migration request using only the
   minimal slug payload above. A retry must reconcile the current slug, marker
   and same IDs; it must never recreate a post or image.
4. Immediately check the old URL with redirects disabled. Require status **301**
   and Location exactly equal to the proposed URL. Reject 302, 404, wrong-host
   destinations, chains or loops. `Transport.verify_slug_redirect(...)` already
   implements this read-only verification and is unit tested.
5. Require the new URL to return 200 without a redirect and one self-canonical
   URL. Re-run the full authenticated and public article/image/link/SEO checks
   with the same IDs. Compare preserved metadata and inspect the page visually.
6. Save an audit receipt with both URLs, IDs, immutable digests and actual
   redirect outcome. Only then update the schedule prompts to use the v2 intake.

If the write times out, inspect the same post before retrying; a slug already
changed is reconciled without another update. If redirect verification fails,
stop and report the live state. Do not create a redirect plugin, change rewrite
rules, recreate the article, or silently expand permissions. A bounded restoration
to the old slug can be proposed for approval after checking for intervening edits;
this proposal does not pre-authorize a rollback or configuration change.

WordPress core records the previous slug when an existing published,
nonhierarchical post changes slug and normally redirects an old slug found on a
404 response with 301. Filters/plugins can affect that behavior; the actual
old-slug redirect was verified after this approved migration.

References:
[WordPress old-slug recording](https://developer.wordpress.org/reference/functions/wp_check_for_changed_slugs/),
[WordPress old-slug redirect](https://developer.wordpress.org/reference/functions/wp_old_slug_redirect/),
[Google descriptive URL guidance](https://developers.google.com/search/docs/crawling-indexing/url-structure).

## Verified outcome and exact read-only rerun

Migration commit: `1a7a644f1fd4bd77dac6890b542365340eb4dc54`.
[Successful migration Action 38073777696](https://github.com/wallyrebel/Pontotoc/actions/runs/38073777696)
reported `verified: true`, `preserved_metadata_verified: true` and
`old_slug_redirect_verified: true`. The only mutation was the slug on post 6010.
The unchanged public source/body/image digests and identity are retained in
`reviewed/receipts/pepa-slug-migration-2026-10-10.json`.
The original audit artifact is `reviewed-audit-38073777696` (artifact 11678241227).
ZIP SHA-256: `32417c358dcf050b4aa77bfb2aba1b7bc75cfd7ab2bcf294b78e7f51f2af3d21`.

Actual checks: old URL returns a direct 301 with Location exactly
`https://pontotocnews.com/pontotoc-news/pepa-password-security-tips/`; the new URL
returns 200 without redirect and has one matching self-canonical. The raw and
public article, headline, excerpt, source links, displayed image/alt, served image
bytes, publication date, GUID and preserved post/media metadata passed. The new
page was also inspected in Chrome. No plugin or site configuration was changed.

The same migration request path now contains `operation: verify-pepa-slug`.
`scripts/pepa_slug_migration.py` is permanently read-only; the mutation branch is
removed. It accepts only the already migrated exact identities and baseline,
verifies the direct redirect and full public article, and returns
`mutation_path_retired: true`. Its only explicit REST operation is GET.

To reverify, manually dispatch **Reviewed public facts transport** on main with
`operation: request` and
`request_path: reviewed/requests/pepa-slug-migration-2026-10-10.json`.
The safe entry point routes that exact path to the retired verifier. In the
existing managed Action environment, the direct equivalent command is:

```sh
python scripts/pepa_slug_migration.py
```

Do not run authenticated commands on the Mac or copy credentials there. All
credentials remain scoped to the existing GitHub Action. New articles use the
normal version-2 contract in `REVIEWED_PUBLISHING.md`.
