# Pontotoc News editorial publisher

Collects local RSS sources, combines updates about the **same event**, writes a
source-backed article, verifies it in a separate model call, then publishes to
WordPress. Sparse sources remain eligible for a later run as related details arrive.
There is no obligation to fill a publishing quota.

## Editorial balance

- Aim for 250–450 words where the reporting supports them; standard articles need
  at least 200 words. Complete, useful local briefs can qualify from **120 words**.
- Require who, what, where, when, and why (documented purpose, consequences or
  significance), at least five distinct facts, and exact supporting source excerpts.
- Combined sources need at least 60 non-repeated source words. Briefs need a
  specific local use, such as event logistics, school notices, public safety or a
  final sports recap. Length alone never qualifies a story.
- The verifier checks the headline, excerpt, body, source relationships, five Ws,
  local relevance, padding, and factual conflicts. Missing or failed checks hold
  the story. No generic filler, invented dates or fabricated context.
- Game updates are grouped before writing. An interim lead is not a final win.
  Ambiguous records and next opponents must not be assigned to a team by guesswork.
- HTML is restricted to basic article formatting. Named source links and an honest
  AI-assistance disclosure are appended by the publisher.
- Use source images when available; do not substitute unrelated stock imagery.
  A missing image does not prevent an otherwise useful story.

These thresholds are editorial safeguards, not Google's ranking requirements.
Google does not prescribe a preferred word count. Original reporting and complete,
accurate answers matter more than length.

## Schedule and capacity

The scheduled GitHub Action runs every **two hours at :17 UTC**. Each run can
publish up to six qualifying stories, with a cached daily limit of 18 posts and
three per feed per run. These are ceilings, not targets. Feed scans look back 72
hours so several short updates can accumulate. Publication history is not written
for held, deferred or dry-run stories.

All scheduled and manual runs share a concurrency group. History is restored from
the newest cache (including the old cache during migration) and saved even when
some stories fail. A separate WordPress source-link duplicate check survives
cache eviction. The cached daily count can reset on cache loss; duplicate checking
still applies. Non-default branches always run without publishing.

## Setup

Use Python 3.11 or newer:

```bash
python -m venv .venv
# Activate the environment for your operating system.
python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `OPENAI_API_KEY`, `WORDPRESS_BASE_URL`, `WORDPRESS_USERNAME` and
`WORDPRESS_APP_PASSWORD`. In GitHub, keep these in Actions secrets. Existing
WordPress status and SMTP notification secrets are supported. The default model is
`gpt-4.1`; override it with the repository variable `EDITORIAL_MODEL` in
Actions, or `OPENAI_MODEL` locally. The model must support structured JSON outputs.
This deliberately supersedes the old nano-model secret in the workflow.

`feeds.yaml` contains documented, validated editorial settings and the original
nine feeds with readable publisher names. Both `category` (legacy) and
`default_category` work. `enabled: false` actually disables a feed. Unknown feed
settings fail validation to catch typos.

## Run and review

```bash
python -m rss_to_wp run --dry-run
python -m rss_to_wp run --dry-run --replay
python -m rss_to_wp run --single-feed "Pontotoc News Feed 4" --dry-run
python -m rss_to_wp run
python -m rss_to_wp status
python -m pytest -q
python -m ruff check src tests
```

A dry run calls the editorial model but does not upload images, create categories,
write posts or mark stories as published. `--replay` is permitted only in dry runs
and ignores local publication history so recent material can be evaluated again.
Dry-run eligibility is **before** remote duplicate checks and publishing ceilings;
it is not a count of new posts that a live run will create.

Actions defaults manual runs to dry-run. The workflow summary and 14-day artifact
include eligibility, holds, reasons, source URLs, proposed articles and verification
results. Any operational error fails the run even if other articles succeeded;
successful posts retain their history. A zero-publication warning calls attention
to weak or stale sources without automatically lowering quality standards.

Review repeated holds and add substantive official reporting when needed. Image
only social posts cannot be interpreted by this text-only pipeline. It does not
invent missing material, scrape arbitrary links or promise daily article volume.
The sheriff and Ecru police feeds were stale at the October 2, 2026 audit; monitoring
the availability of source material is necessary for sustained output.

## Deployment and recovery

1. Run the regression suite and a manual dry run with replay on the candidate branch.
2. Inspect the editorial artifact, especially combined stories and brief decisions.
3. Merge the tested change into `main`; future scheduled runs use that code.
4. If needed, revert the merge to restore the old workflow. Do not clear history
   as a troubleshooting shortcut. No historic articles are bulk deleted by this code.

Model verification reduces error risk but does not replace human editorial review.
Prioritize review of public-safety, health and legal stories, and publish corrections
when needed. Improving the publisher alone cannot guarantee indexing or AdSense revenue.

References: [Google's people-first content guidance](https://developers.google.com/search/docs/fundamentals/creating-helpful-content),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
