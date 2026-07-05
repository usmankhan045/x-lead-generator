# X Lead Generator

Autonomous Twitter/X pain-point lead hunter. Twice a day it searches X for tweets where
business owners describe problems you can solve (manual/repetitive work, needing an app or
website, Shopify/e-commerce ops pain, coaching/real-estate ops pain), scores each with an
LLM, drafts two human-sounding replies + a follow-up DM, and posts everything to Discord.
You read the Discord card and post the reply yourself.

**You post every reply manually.** X blocks and suspends keyword-triggered auto-reply bots
(Feb/Mar 2026 enforcement). This tool only ever *reads* X (via Apify — no login, not your
account) and hands you drafts. That is the only durable architecture.

## How it works

```
GitHub Actions (cron 2x/day)
  scrape (Apify)  →  pre-filter (free rules)  →  mark seen  →  LLM score + confidence
     →  draft 2 styled replies + DM  →  Discord embeds  →  log to Supabase
```

- **Scraper** (`src/scraper.py`) — Apify actor, configurable, actor-agnostic normalizer.
- **Pre-filter** (`src/prefilter.py`) — drops >24h-old, already-seen, spam, thin/junk accounts. Free, no LLM.
- **Scorer** (`src/scorer.py`) — weighted 0-100 rubric + separate confidence %, tweet-type, market check.
- **Drafter** (`src/drafter.py`) — picks 2 of 20 styles (rotated so no two leads sound alike), writes drafts, a second model audits for AI tells.
- **Discord** (`src/discord_notify.py`) — one embed per lead, plus an end-of-run digest.

## Guarantees baked in

- **No tweet older than 24h** is ever processed or delivered (hard rule, checked at process time).
- **No tweet scanned twice** — every pulled tweet ID is written to `x_seen_tweets` before scoring.
- **Target markets only** — authors confirmed outside US/CA/UK/IE/AU/NZ/W-EU are dropped; unknown-location leads are delivered with lowered confidence and a `⚠` flag.
- **No fabricated proof** — experience claims come only from `prompts/proof_library.md`.
- **Groq free tier only** — no paid LLM providers.

## Setup

1. `python -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and fill in tokens (all free tiers):
   - Apify (`APIFY_TOKEN`), Groq (`GROQ_API_KEY`), Supabase (`SUPABASE_URL`/`SUPABASE_KEY`), Discord webhook.
3. Create the Supabase tables: run `db/schema.sql` in the Supabase SQL editor.
4. In Apify, set a **max cost per run** on the actor as a billing guard.
5. Add the same secrets to the GitHub repo (Settings → Secrets → Actions). The workflow
   `.github/workflows/hunt.yml` runs twice daily and is also runnable via **Run workflow**.

## Run it

```bash
# fully offline smoke test — no keys, no network (fixture tweets + mock LLM)
.venv/bin/python tests/test_pipeline.py

# offline single run with printed Discord payloads
.venv/bin/python src/main.py --fixture fixtures/sample_tweets.json --mock-llm --dry-run --print-sink

# live scrape but no DB writes, posts to your test webhook
.venv/bin/python src/main.py --dry-run

# full live run
.venv/bin/python src/main.py
```

## Tuning

- **Queries** live in `config/queries.yaml` — plain config. Validate a new query by pasting it
  into X search first (aim for ≥20-30% relevance) before enabling. Watch per-query hit rates
  in the Discord digest and rewrite anything under ~10%.
- **Styles** live in `prompts/comment_styles.md`. Each embed names the styles it used; cull
  the ones you never pick.
- **Thresholds / models / markets** live in `config/settings.yaml`.
- **Your proof** lives in `prompts/proof_library.md` — keep it truthful and current.

## Before you launch (your X profile is the landing page)

Good replies drive profile clicks; the profile converts or kills the lead. Prep first:
bio that says what you do + a proof point, a pinned case-study tweet, 10-30 competence posts,
and X Premium (replies rank higher). Keep manual replies to ~5-15/day, never identical text.
