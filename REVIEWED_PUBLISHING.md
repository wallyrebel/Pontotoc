# Reviewed public-facts publishing

This route transports an already researched and reviewed article to Pontotoc News.
It does not fetch RSS to generate prose, call a language model, pick stock photos,
or schedule editorial work. `feeds.yaml` remains the saved source inventory.
The existing RSS automatic schedule is retired after the authorized cutover;
its remaining manual inspection workflow is dry-run only.

Jon's editorial plan is at least two useful articles daily, more when warranted,
plus a nightly news scan and publication of items he explicitly sends to publish.
If there are too few standalone local stories, verified local summaries or
statewide news, sports and weather summaries are approved. Assistant schedules
are owned by the parent task: **9 a.m., 4 p.m., and 7:30 p.m. America/Chicago**.
The nightly scan may produce an additional worthwhile reviewed article.
This repository creates no assistant schedules or new cron publisher.

## Exact intake files

Use one article per request:

- `reviewed/articles/<name>.json`: strict version-1 editorial package.
- `reviewed/assets/<name>.png` or `.jpg`: original or authorized featured image.
- `reviewed/requests/<name>.json`: digest-bound transport request.
- `scripts/reviewed_publish.py`: validator and bounded WordPress REST transport.
- `scripts/reviewed_action.py`: safe Action entry point; no shell input expansion.
- `.github/workflows/reviewed_publish.yml`: managed credential runner.
- `data/reviewed-audit/report.json`: selected IDs, digests, outcome, public URL or
  safe failure classification. Uploaded as `reviewed-audit-<run_id>` for 90 days.

The launch package `reviewed/articles/pepa-password-reminder-2026-10-10.json`
is a complete example. Its corresponding request is now **publish**, following
the parent-reviewed launch and successful public verification.
The adjacent `.html` contains exactly the generated article body for review.
The PEPA source art was inspected as evidence only and is not included for reuse.
`scripts/create_pepa_graphic.py` renders the original 1600×900 lock illustration
using macOS Arial fonts; the checked-in PNG is the actual reviewed asset.

## Article contract and editorial responsibility

The JSON accepts only the fields demonstrated by the launch example. Unknown
fields, missing evidence, unchecked review items, inaccessible files, invalid
URLs, future verification timestamps, and mismatched image bytes are rejected.

`event_keys` are stable, lowercase, feed-independent identities for the reported
events (example: `ms:pontotoc:pepa:2026-10-08:password-reminder`). Keep the same keys
when retrying. Each summary lists the events it covers. Never change an event key
to bypass a duplicate guard. The article ID is SHA-256 of sorted event keys joined
with newlines. The full ID supplies the post slug and immutable content marker.

Every source has an ID, HTTPS URL, title, publisher, publication timestamp (or
explicit `null` for undated material), verification timestamp, verification URL,
and `role`: `event` or `background`. Event source URL reuse blocks publication
across feeds and legacy posts. Background guides may support distinct new events;
do not classify an event's original report as background to bypass dedupe.
Prefer event-specific dated URLs for daily weather or statewide summaries.
Facebook numeric post IDs are normalized across page and mobile URL aliases;
tracking parameters and trailing slashes are ignored for source dedupe.

Normally `verification_url` equals `url`. For a login-gated Facebook permalink,
it may be its exact existing saved feed URL from `feeds.yaml`; the run must find
the actual permalink in that feed. The reader-facing article still links the
original permalink. The assistant must inspect the linked source graphic and
record its evidence, rather than infer facts from the feed's generic headline.
Transport confirms evidence availability and the exact outgoing public links;
it cannot guarantee Facebook will show a permalink to readers without login.

Each fact records its statement, source IDs, short evidence, date context,
locality, identities and statistics. Record `None asserted` when appropriate;
never fill missing data with guesses. Every paragraph, headline and excerpt must
reference ledger fact IDs. The body is generated from escaped plain paragraphs,
image credit, linked sources and dedupe markers; arbitrary HTML is not accepted.
The original copy must be coherent reported prose with a useful local lead.

`review.decision` must be `publish`, and all ten named checks must be `true`:
dates, locality, identities, statistics, source support, coherent prose, no
invented quotes/context, public facts only, no allegations/private sensitive
material, and image rights. These are the reviewing assistant's attestations,
not a claim that software verifies editorial truth. Research and editorial
judgment happen before submission. Check the saved feeds and corroborating
primary sources, record actual event dates and time zones, distinguish guidance
from local statistics, and search the site for semantic event overlap too.

Images require a local file, full SHA-256, descriptive alt text, credit, rights
(`owned`, `permission`, `public_domain`, or `licensed`) and a rights reference.
No image is scraped or downloaded for publication by the transport. PNG/JPEG
bytes, dimensions, pixel count and size are validated. Media identities combine
the article ID and image digest. Served image dimensions and decoded pixels are
checked before publication and in final verification, allowing modest JPEG
recompression. A shared or ambiguous media identity stops publication.

`submission.kind` is `assistant_review` or `user_submitted`. Both require
`publish_intent: true` and a concise authorization reference. A user-submitted
item must have an explicit instruction to publish; a forwarded item alone is
not enough. The same sourcing and editorial checks apply.

## Submit or retry a reviewed article

No WordPress credentials belong on the Mac, in JSON, in git, or in artifacts.
Only the Action receives the existing managed `WORDPRESS_BASE_URL`,
`WORDPRESS_USERNAME` and `WORDPRESS_APP_PASSWORD`. Its site is pinned to
`https://pontotocnews.com`; authenticated redirects are rejected.

Create a request using Python rather than manually copying a digest:

```python
from pathlib import Path
import hashlib, json
article = Path('reviewed/articles/<name>.json')
request = {'schema_version': 1, 'article_path': str(article),
           'article_sha256': hashlib.sha256(article.read_bytes()).hexdigest(),
           'mode': 'dry-run'}
Path('reviewed/requests/<name>.json').write_text(json.dumps(request, indent=2) + '\n')
```

Offline checks (no managed credentials or network required):

```sh
python scripts/reviewed_publish.py --request reviewed/requests/<name>.json --validate
PYTHONPATH=src python -m pytest -q
```

With the supported authenticated Mac git route, commit the article, authorized
asset and exactly one new/changed request, then `git push origin main`. Only
one request per push is accepted. Changes to transport code alone launch the
authenticated read-only capability probe. A request push launches that request's
mode. Mere article or asset changes do not launch publishing.

Manual alternative: GitHub Actions → **Reviewed public facts transport** →
**Run workflow** on **main**. Select `operation: probe` for the all-status
read-only check, or `operation: request` with the exact request path to run its
stored mode. A retry of the same request uses the same deterministic identities.
No connector writes or new GitHub tokens are needed.

After the dry run and final article/image review, the authorized operator can
change only the request's `mode` to `publish`, commit that request, and push main.
The article digest must still match. The current launch article was explicitly
approved by the parent and published successfully. Do not publish filler or test stories.

## Failure, recovery and verification

The new and existing RSS workflows share `pontotoc-wordpress-publication` with
`cancel-in-progress: false`. GitHub's concurrency group serializes their runs;
it is not a durable queue (GitHub may replace an older pending run). Never assume
each pushed request ran. Submit one article, inspect its result, then send the
next. Redispatch any displaced request from the saved path. Other WordPress
editors and external publishers must avoid simultaneous writes for the same
event; the REST API has no atomic unique-event constraint. Existing old runs
started before the lock was deployed must finish before any reviewed publication.

Before a write, the route checks managed account capabilities and discovers
status enums from WordPress's OPTIONS schema. It scans **every advertised
lookup status** with complete authenticated pagination: posts include draft,
future, pending, private, trash, inherit and auto-draft; the attachment controller
advertises inherit, private and trash. Errors,
missing pagination evidence, changing collection counts, duplicate identities
or conflicting source/events stop the run. No cache is the source of truth.
The old RSS client's existing fail-open duplicate behavior is not used by this
route, and its workflow can no longer publish.

A new item starts as a draft containing its exact reviewed body and markers.
The media upload carries deterministic filename, slug and description in one
multipart request. The route reconciles through all-status scans after create
and upload, checks served image bytes, binds the image to the exact draft, then
publishes. On a timeout/failed write, stop and rerun the same request: already
committed draft/media/publication is reconciled rather than recreated. Changed,
trashed or mismatched existing content is never overwritten or restored. Resolve
the discrepancy through review instead of changing IDs. No automatic POST retry
is performed within a failed run.

Success requires matching authenticated raw content, public REST title/body/
excerpt, public page headline and every reported paragraph, all expected source
links, displayed featured image and served image verification. A green Action
without `verified: true` is not a publication receipt. A failed public check may
mean a post is already live; retry to verify it, never recreate it. Inspect the
public page visually as the final editorial check, especially the image crop.

Official API basis: [post status collection schema](https://developer.wordpress.org/reference/classes/wp_rest_posts_controller/get_collection_params/),
[posts](https://developer.wordpress.org/rest-api/reference/posts/) and
[media](https://developer.wordpress.org/rest-api/reference/media/).

## Completed launch and cutover

The parent confirmed the enabled assistant schedules for 9 a.m., 4 p.m. and
7:30 p.m. America/Chicago, then authorized the conditional cutover after the
first real article passed public verification. No assistant schedule was created
by this repository task.

On October 10, 2026, the approved PEPA article was published as post **6010** with
featured media **6011**. The initial publication run timed out; the unchanged
request resumed through deterministic reconciliation and returned `verified: true`
in [Action 38069851928](https://github.com/wallyrebel/Pontotoc/actions/runs/38069851928).
Its receipt artifact is `reviewed-audit-38069851928`. The article digest is
`c7d375cd0ae702a0c7a7dc3446e3506014ccecbc558dd9bfccde11f887f324df`.
The served image digest is
`50e7376cf918e8c87b052a5cdf23b005c413e9f0a76eb0fa55fa9c9faee92cf4`.
The live headline, seven paragraphs, full lock illustration, credit and both
source links were also inspected in Chrome. [Live article](https://pontotocnews.com/pontotoc-news/pontotoc-reviewed-8f7432d95ed4486809f126f35492ce5ecc365f86b55098c6c4e1fee8927b01a4/).

Before cutover, GitHub's active, queued, pending, waiting and requested run lists
contained no legacy publisher runs. The old workflow's schedule trigger was
removed. Its sole remaining trigger is manual dispatch on main with `dry_run`
equal to `true`; the CLI command unconditionally includes `--dry-run`. This
prevents automatic RSS generation and prevents legacy workflow publication.
`feeds.yaml`, unrelated workflows and completed read-only correction verifiers
remain unchanged. Never reactivate the post 5997 or post 5882 write paths.
