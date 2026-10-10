Post 5997 correction — local review only

Prepared from repository main commit `2fe6c6e64c57b4f7f3c2536bde9ff191a0bcadd9`.
No AGENTS.md, .agents directory, or repository skills are present in this checkout.
The retired post 5882 files, all existing workflows and all schedules are unchanged.
No credentials were retrieved, copied, created or changed. No GitHub connector
writes, git pushes, WordPress mutations or workflow dispatches were performed.

Reviewed headline: Ashley scores twice as Pontotoc beats West Point 23-6 in region opener

The complete parent-reviewed body is `tests/fixtures/post5997/after-raw.html`.
The proposed excerpt is: Nolan Ashley ran for two touchdowns and Tim Jones
intercepted two passes as Pontotoc beat West Point 23-6 in its Region 1-5A opener.
This removes the existing excerpt's unsupported description of Courtland Pass
as injured. The parent should include this excerpt in final payload approval.

Existing URL and slug:
https://pontotocnews.com/pontotoc-news/pontotoc-sophomore-quarterback-nolan-ashley-leads-warriors-past-west-point/

Existing date `2026-10-10T08:36:42`; date_gmt `2026-10-10T13:36:42`.
Public before-state is captured in `tests/fixtures/post5997/before-public.json`.
Current featured media 5996 is a 940×627 Pexels JPEG, not the supplied photo.
Its before-state is in `tests/fixtures/post5997/before-media.json`.
Authenticated raw before-state was captured through a read-only managed run and
is retained locally, with only raw title/body/excerpt SHA-256 hashes committed
in `tests/fixtures/post5997/before-raw-sha256.json`. Its rendered content
matches the public snapshot. The initial comparison now handles WordPress's
edit-only block_version field, and guards the exact authenticated raw state.

The exact attached Library image was materialized on the Mac with the current
unmodified helper, verified by Pillow, and inspected visually. The source asset
is `assets/post5997/featured.jpg`, 2048×1536, 345,053 bytes. SHA-256:
`069a5e056449afe14df2a0b3e68d96483d47df89cce052a5d925e064c58aef29`.
Use descriptive alt text from source.json; do not identify the pictured player.

Publication plan, pending parent authorization:

1. Review the headline, exact HTML, proposed excerpt and supplied image. Commit
   and push only these scoped new files using existing authenticated git.
2. Use the exact commit message `Review Pontotoc post 5997 correction without writes`
   for the initial git push. This triggers the new read-only plan through the
   same existing git/push mechanism as post 5882, without connector writes or
   workflow-dispatch API calls. The runner
   uses only the existing WORDPRESS_BASE_URL, WORDPRESS_USERNAME and
   WORDPRESS_APP_PASSWORD secrets. Inspect its authenticated snapshot and media
   inventory. All matching-dimension JPEGs are checked by exact bytes, including
   renamed imports and uploads from uncertain earlier attempts. More than one
   match or conflicting alt text/name stops for review.
3. With final publication authorization, change only APPLY_AUTHORIZED to True
   in the scoped script and push with the exact commit message
   `Correct Pontotoc post 5997 using reviewed Athletics facts and supplied image`.
   The default False gate blocks apply before any network request. Reuse an
   exact existing image or upload once under a deterministic digest filename.
   Set and verify its alt text. Recheck post state before the sole post update.
   Send only title, content, excerpt and the reconciled featured_media integer.
   Never send slug, dates, status, author, categories, tags or unrelated metadata.
4. Verify exact authenticated raw title/body/excerpt, image bytes and alt text,
   every unrelated before-state field, public REST content and the public page.
   Failed or uncertain writes are not retried in the same run. A later reviewed
   run reconciles state before doing anything; an already completed correction
   performs verification only. Stop on drift or ambiguity.
5. After verified publication, apply the separately prepared retirement patch,
   test and push it via existing git. This removes the write function, CLI apply
   switch and workflow apply step. Keep the workflow as a read-only audit and
   leave every existing schedule and post 5882 file untouched.
   The patch is `../retire-post5997.patch`; it targets the future approved
   APPLY_AUTHORIZED=True state. Use the exact retirement commit message
   `Verify Pontotoc post 5997 correction without writes` to trigger verification.

Validation: 33 local tests passed across the new correction and retired post
5882 suite. A separate retired-code copy passed 6 read-only verification tests.
Both scripts compile, the workflow parses as YAML, and diffs confirm the existing
RSS workflow, retired correction workflow and retired correction script are
unchanged. The review payload is also available at
`../post5997-review-payload.json`; its null featured_media is a review placeholder
to be replaced with the reconciled numeric ID before any WordPress post update.

Limitations: WordPress does not provide atomic compare-and-swap for these REST
updates. Immediate snapshot rechecks and workflow serialization reduce the race,
but an editor could still change the post between the last GET and POST. There
is no automatic rollback or deletion of old media. Audit artifacts permit safe
comparison and a deliberate recovery decision. Public before-state was captured
locally; authenticated preparation requires a later authorized managed run.
