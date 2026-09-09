# AIF-C01 Daily Question Agent — Setup Guide

This repo runs a daily pipeline that pulls the latest AWS AI Practitioner
exam info, verifies it, generates 100 new practice questions, and publishes
them to a static quiz site — for **$0/month infrastructure cost**, only
paying per-token for the LLM calls (roughly $1–5/month at this volume).

## What's inside

```
.github/workflows/daily-question-generation.yml   # the daily cron job
scripts/
  config.py         # source URLs, domain weights, model choice — edit here
  ingest.py         # step 1: pulls AWS docs + RSS, diffs vs. yesterday
  verify.py         # step 2: promotes only corroborated facts
  generate.py       # step 3: writes new questions grounded in verified facts
  qa_dedupe.py      # step 4: schema/grounding/duplicate checks + audit sample
  publish.py        # step 5: appends accepted questions to the live site
  run_pipeline.py   # orchestrates all five steps
site/
  index.html        # the quiz site (fetches questions.json at load — you built this)
  questions.json     # seeded with your original 200, verified questions
  manifest.json      # "N questions, last updated <date>" shown on the site
data/                # dated audit trail: every day's snapshot, verified facts,
                      # candidates, accepted, and rejected questions
requirements.txt
```

## One-time setup (15 minutes)

1. **Create a new GitHub repo** and push everything in this folder to it.

2. **Get an Anthropic API key** at console.anthropic.com if you don't have
   one already.

3. **Add it as a repo secret:**
   Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: `ANTHROPIC_API_KEY`
   - Value: your key

4. **Enable GitHub Pages:**
   Repo → Settings → Pages → Source: "Deploy from a branch" → Branch: `main`,
   folder: `/site`. Your quiz will be live at
   `https://<your-username>.github.io/<repo-name>/`.

5. **Test it manually before waiting for the schedule:**
   Repo → Actions tab → "Daily AIF-C01 question generation" → "Run workflow"
   button. Watch the logs — you should see all 5 steps complete and a commit
   land with today's date.

6. That's it. From here it runs itself daily at 09:00 UTC (edit the `cron:`
   line in the workflow file to change the time).

## Checking on it

- **Actions tab** shows every run's logs — did ingest find anything new,
  how many questions were generated vs. accepted, any failures.
- **`data/rejected/<date>.json`** — read this occasionally. If you see a lot
  of `ungrounded` or `failed_audit_spotcheck` rejections, something's off
  with the generation prompt or the source material being fed in; if you see
  mostly `duplicate_of_existing`, that's actually healthy — it means the
  question bank is saturating a domain and the model is running low on new
  ground to cover.
- **`data/verified_facts/<date>.json`** — this is your audit trail for "what
  changed in AWS's docs today and did the agent trust it."

## Cost notes

- **Infrastructure: $0/month.** GitHub Actions free tier (2,000 min/month)
  covers this daily job many times over; GitHub Pages hosting is free.
- **LLM tokens: roughly $1–5/month** at 100 questions/day on Haiku-tier
  pricing. If you want to cut this further, lower `DAILY_QUESTION_TARGET`
  in `config.py`, or only run the workflow on weekdays by adjusting the cron
  schedule.
- Check current Anthropic API pricing at anthropic.com/pricing before
  relying on the estimate above — rates do change.

## Adjusting the daily volume or domain split

Edit `scripts/config.py`:
- `DAILY_QUESTION_TARGET = 100` — change to whatever number you want.
- `DOMAIN_WEIGHTS` — only change this if AWS publishes a new exam guide with
  different domain percentages (check the source URLs in `CANONICAL_SOURCES`
  periodically — if AWS restructures those pages, `ingest.py`'s scraping
  logic may need a small update).

## Known limitations, on purpose

- The RSS-based "tier 2" verification is intentionally conservative — it
  only promotes a news item to "verified" if it corroborates against the
  official in-scope/out-of-scope service list. Real, meaningful changes
  (a new service added or removed from the exam) will always be caught via
  the canonical docs diff regardless of whether any blog covered it.
- The audit spot-check in `qa_dedupe.py` only reviews ~15% of each day's
  accepted batch. That's a deliberate cost/thoroughness tradeoff — raise
  `AUDIT_SAMPLE_RATE` in `config.py` if you'd rather spend more tokens for
  more coverage.
- This pipeline was smoke-tested end-to-end with mocked data (no real AWS
  network access from the build environment) — the logic is verified sound,
  but watch the first few real scheduled runs to confirm the live AWS pages
  parse the way `ingest.py` expects, since AWS does restructure doc pages
  from time to time.
