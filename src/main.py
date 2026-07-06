"""Pipeline orchestrator.

Run modes:
  python src/main.py                      # live run (needs all secrets)
  python src/main.py --dry-run            # scrape live, but no DB writes, post to test webhook
  python src/main.py --fixture fixtures/sample_tweets.json --mock-llm --dry-run
                                          # fully offline: fixture tweets + mock LLM, no network

The run_pipeline() core takes an injected db so tests can call it twice with one MemoryDB
to prove the never-scan-twice guarantee.
"""
from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import timedelta
from typing import Any

import db as db_mod
import discord_notify
import drafter
import llm
import prefilter
import scorer
import scraper
from util import FIXTURES_DIR, env, get_logger, load_prompt, load_queries, load_settings, now_utc

log = get_logger("main")


def rotate_queries(queries: list[dict], per_run: int) -> list[dict]:
    """Deterministically rotate which queries run, so consecutive runs cover different niches."""
    if per_run >= len(queries):
        return queries
    n = len(queries)
    t = now_utc()
    slot = (t.timetuple().tm_yday * 2 + (0 if t.hour < 12 else 1))  # unique per AM/PM per day
    offset = (slot * per_run) % n
    return [queries[(offset + i) % n] for i in range(per_run)]


def load_fixture(path: str, query_niche: dict[str, str]) -> list[dict]:
    """Load fixture items (raw-actor-ish shape with relative ages) → normalized tweets.

    Relative ages (_age_hours, author._account_age_days) are converted to absolute
    timestamps at load time so fixtures never go stale and the freshness test is stable.
    """
    with open(path) as f:
        items = json.load(f)
    now = now_utc()
    out = []
    for it in items:
        it = dict(it)
        age_h = it.pop("_age_hours", 1)
        it["createdAt"] = (now - timedelta(hours=age_h)).isoformat()
        author = dict(it.get("author") or {})
        acct_age = author.pop("_account_age_days", 400)
        author["createdAt"] = (now - timedelta(days=acct_age)).isoformat()
        it["author"] = author
        qid = it.pop("_query_id", None)
        niche = it.pop("_niche", query_niche.get(qid) if qid else None)
        norm = scraper.normalize_tweet(it, qid, niche)
        if norm:
            out.append(norm)
    return out


def run_pipeline(
    db,
    settings: dict,
    queries: list[dict],
    *,
    fixture: str | None = None,
    dry_run: bool = False,
    discord_sink: list | None = None,
) -> dict[str, Any]:
    t = now_utc()
    run_id = t.strftime("run-%Y%m%d-%H%M%S")
    query_niche = {q["id"]: q.get("niche") for q in queries}

    # Read the PREVIOUS run's start BEFORE creating this run's row — otherwise the
    # since-window would be set to "now" (this run reading itself) and find no tweets.
    last_run = db.last_run_started_at()
    db.create_run(run_id)

    # 1-2. GATHER from every enabled source (all feed the same pipeline)
    if fixture:
        tweets = load_fixture(fixture, query_niche)
        est_cost = 0.0
    else:
        tweets, est_cost = [], 0.0
        srcs = settings.get("sources", {})
        if srcs.get("x", {}).get("enabled", True):
            xt, xc = scraper.scrape(settings, queries, last_run, env("APIFY_TOKEN", required=True))
            tweets += xt
            est_cost += xc
        if srcs.get("hackernews", {}).get("enabled", False):
            import hn

            ht, hc = hn.fetch_leads(settings, last_run)
            tweets += ht
            est_cost += hc
    scraped = len(tweets)

    # 3. DEDUP — never scan twice (DB is source of truth)
    unseen = db.filter_unseen([t["tweet_id"] for t in tweets])
    tweets = [t for t in tweets if t["tweet_id"] in unseen]
    seen_skipped = scraped - len(tweets)

    # 4. PRE-FILTER (cheap rules; DB already removed seen, so pass empty seen set)
    survivors, drop_reasons = prefilter.run(tweets, settings, seen_ids=set())

    # 5. MARK SEEN — everything we pulled and looked at, BEFORE any LLM call.
    #    Marking the full unseen batch (not just survivors) means junk is never re-evaluated.
    db.mark_seen([t["tweet_id"] for t in tweets], run_id)

    # 6. SCORE (drops confirmed out-of-market)
    scored, score_stats = scorer.classify(survivors, settings)
    for s in scored:
        s["_age_hours"] = round((now_utc() - s["created_at"]).total_seconds() / 3600, 1) if s.get("created_at") else -1

    deliver_th = settings["scoring"]["deliver_threshold"]
    border_th = settings["scoring"]["borderline_threshold"]
    to_deliver, review = [], []
    for lead in scored:
        t = _tier(lead, deliver_th, border_th)
        if t == "deliver":
            to_deliver.append(lead)
        elif t == "review":
            review.append(lead)

    # 7. DRAFT — both delivered AND review-tier leads get drafts (review = your judgment).
    styles = drafter.parse_styles(load_prompt("comment_styles.md"))
    window = settings["drafting"]["recent_style_exclusion"]
    proof = load_prompt("proof_library.md")
    # Rolling window of the last `window` leads' style-sets (DB history + within-run),
    # bounded so a small tweet-type pool can never be fully excluded and forced to repeat.
    recent: deque[list[str]] = deque(maxlen=window)
    for s in db.recent_delivered_styles(window):
        recent.append([s])
    # Draft highest-score first so style rotation favours the best leads.
    deliver_ids = {l["tweet_id"] for l in to_deliver}
    for lead in sorted(to_deliver + review, key=lambda l: l["_score"]["score"], reverse=True):
        excluded = {s for group in recent for s in group}
        drafts = drafter.draft_for_lead(lead, settings, styles, excluded, proof)
        lead.update(drafts)
        recent.append(drafts["styles_used"])
        status = "delivered" if lead["tweet_id"] in deliver_ids else "borderline"
        db.insert_lead(_lead_row(lead, run_id, status))

    # 8. DELIVER + digest
    stats = {
        "tweets_scraped": scraped,
        "seen_skipped": seen_skipped,
        "prefiltered": len(survivors),
        "scored": score_stats["scored"],
        "delivered": len(to_deliver),
        "borderline": len(review),
        "est_cost_usd": est_cost,
        "query_stats": _query_stats(queries, scored, to_deliver),
        "drop_reasons": drop_reasons,
        "out_of_market": score_stats["dropped_out_of_market"],
    }

    lead_webhook = _webhook(dry_run)
    digest_webhook = env("DISCORD_DIGEST_WEBHOOK_URL") or lead_webhook
    review_webhook = env("DISCORD_REVIEW_WEBHOOK_URL") or lead_webhook   # falls back to main
    hn_webhook = env("DISCORD_HN_WEBHOOK_URL") or lead_webhook           # dedicated HN channel

    # Route by source so Hacker News leads land in their own channel, never mixed with X.
    is_hn = lambda l: l.get("source") == "hn"  # noqa: E731
    x_deliver = [l for l in to_deliver if not is_hn(l)]
    x_review = [l for l in review if not is_hn(l)]
    hn_deliver = [l for l in to_deliver if is_hn(l)]
    hn_review = [l for l in review if is_hn(l)]

    if lead_webhook or discord_sink is not None:
        discord_notify.deliver_leads(lead_webhook, x_deliver, discord_sink, tier="LEAD")
        discord_notify.deliver_leads(review_webhook, x_review, discord_sink, tier="REVIEW")
        discord_notify.deliver_leads(hn_webhook, hn_deliver, discord_sink, tier="LEAD")
        discord_notify.deliver_leads(hn_webhook, hn_review, discord_sink, tier="REVIEW")
        discord_notify.deliver_digest(digest_webhook, run_id, stats, review, discord_sink)
    else:
        log.warning("no Discord webhook configured; skipping delivery")

    db.finish_run(run_id, {k: stats[k] for k in (
        "tweets_scraped", "seen_skipped", "prefiltered", "scored", "delivered", "borderline", "est_cost_usd"
    )} | {"query_stats": stats["query_stats"]})

    log.info("run %s done: %s", run_id, {k: stats[k] for k in ("tweets_scraped", "delivered", "borderline")})
    return stats


def _tier(lead: dict, deliver_th: int, border_th: int) -> str:
    """Decide deliver / review / drop for a scored lead.

    X leads: use the composite score vs thresholds.
    HN 'SEEKING FREELANCER' leads are pre-qualified buyers (a company hiring now), so their
    composite score is noisy (job posts lack 'pain/urgency' language and models disagree).
    Gate them on the STABLE signals instead — service fit + in-market — so a real Swiss AI
    role doesn't get dropped just because one model scored its "pain" low this run.
    """
    s = lead["_score"]
    if lead.get("source") == "hn":
        if s["market"]["in_target"] is False:  # confirmed outside target -> drop
            return "drop"
        fit = s["subscores"].get("fit", 0)
        if fit >= 12:
            return "deliver"
        if fit >= 8:
            return "review"
        return "drop"
    score = s["score"]
    if score >= deliver_th:
        return "deliver"
    if score >= border_th:
        return "review"
    return "drop"


def _lead_row(lead: dict, run_id: str, status: str) -> dict:
    s = lead["_score"]
    return {
        "tweet_id": lead["tweet_id"],
        "author_id": lead.get("author_id"),
        "handle": lead.get("handle"),
        "author_name": lead.get("author_name"),
        "text": lead.get("text"),
        "bio": lead.get("bio"),
        "location": lead.get("location"),
        "followers": lead.get("followers"),
        "tweet_url": lead.get("url"),
        "niche": lead.get("niche") or s.get("niche"),
        "tweet_type": s.get("tweet_type"),
        "query_id": lead.get("query_id"),
        "score": s.get("score"),
        "confidence": s.get("confidence"),
        "score_json": s,
        "styles_used": lead.get("styles_used"),
        "reply_draft_a": lead.get("reply_draft_a"),
        "reply_draft_b": lead.get("reply_draft_b"),
        "dm_draft": lead.get("dm_draft"),
        "status": status,
        "tweet_created_at": lead["created_at"].isoformat() if lead.get("created_at") else None,
        "_run": run_id,
    }


def _query_stats(queries: list[dict], scored: list[dict], delivered: list[dict]) -> dict:
    stats = {q["id"]: {"scraped": 0, "delivered": 0} for q in queries}
    for s in scored:
        qid = s.get("query_id")
        if qid in stats:
            stats[qid]["scraped"] += 1
    for d in delivered:
        qid = d.get("query_id")
        if qid in stats:
            stats[qid]["delivered"] += 1
    return stats


def _webhook(dry_run: bool) -> str | None:
    if dry_run:
        return env("DISCORD_TEST_WEBHOOK_URL") or env("DISCORD_WEBHOOK_URL")
    return env("DISCORD_WEBHOOK_URL")


def main() -> None:
    ap = argparse.ArgumentParser(description="X pain-point lead generator")
    ap.add_argument("--dry-run", action="store_true", help="no DB writes, post to test webhook")
    ap.add_argument("--fixture", help="path to fixture JSON instead of live scraping")
    ap.add_argument("--mock-llm", action="store_true", help="use deterministic mock LLM (offline)")
    ap.add_argument("--print-sink", action="store_true", help="print captured Discord payloads (dry-run)")
    args = ap.parse_args()

    settings = load_settings()
    queries = rotate_queries(load_queries(), settings["scraper"]["queries_per_run"])
    llm.configure(settings["llm"]["throttle_seconds"], settings["llm"]["max_retries"])

    if args.mock_llm:
        import mock_llm

        llm.set_mock(mock_llm.call_json)
        log.info("LLM mocked (offline mode)")

    db = db_mod.make_db(args.dry_run, env("SUPABASE_URL"), env("SUPABASE_KEY"))
    sink: list | None = [] if (args.dry_run and args.print_sink) else None

    stats = run_pipeline(db, settings, queries, fixture=args.fixture, dry_run=args.dry_run, discord_sink=sink)

    if sink is not None:
        print("\n=== captured Discord payloads ===")
        print(json.dumps(sink, indent=2, default=str))
    print("\n=== run stats ===")
    print(json.dumps(stats, indent=2, default=str))


if __name__ == "__main__":
    main()
