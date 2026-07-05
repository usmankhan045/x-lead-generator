"""Offline end-to-end verification: fixture tweets + mock LLM, no network.

Run: python tests/test_pipeline.py
Proves the guarantees the build promised:
  - freshness: nothing older than 24h is delivered
  - market: confirmed out-of-market authors are dropped
  - prefilter: spam / thin accounts dropped
  - dedup: a second run over the same DB delivers nothing (never scan twice)
  - drafting: delivered leads get 2 style-labeled drafts + a DM
  - style rotation: consecutive delivered leads don't reuse a style
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import db as db_mod  # noqa: E402
import llm  # noqa: E402
import mock_llm  # noqa: E402
from main import run_pipeline  # noqa: E402
from util import load_queries, load_settings  # noqa: E402

FIXTURE = str(ROOT / "fixtures" / "sample_tweets.json")


def main() -> int:
    llm.set_mock(mock_llm.call_json)
    settings = load_settings()
    queries = load_queries()  # all queries so every fixture query_id resolves
    db = db_mod.MemoryDB()

    sink1: list = []
    stats1 = run_pipeline(db, settings, queries, fixture=FIXTURE, dry_run=True, discord_sink=sink1)

    delivered = [l for l in db.leads if l["status"] == "delivered"]
    delivered_ids = {l["tweet_id"] for l in delivered}
    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    # freshness: stale 30h tweet must never appear
    check("2007" not in db.seen or "2007" not in delivered_ids, "stale tweet 2007 delivered")
    check("2007" not in delivered_ids, "stale tweet 2007 was delivered (freshness rule broken)")

    # out-of-market: India author (2005) dropped
    check("2005" not in delivered_ids, "out-of-market tweet 2005 (India) was delivered")

    # spam (2008) and duplicate (2010) dropped by prefilter
    check("2008" not in delivered_ids, "spam tweet 2008 was delivered")
    check("2010" not in delivered_ids, "duplicate tweet 2010 was delivered")

    # at least the strong US/UK/CA leads delivered
    check(len(delivered) >= 2, f"expected >=2 delivered, got {len(delivered)}")

    # every delivered lead has 2 drafts + dm + 2 styles
    for l in delivered:
        check(bool(l["reply_draft_a"]), f"{l['tweet_id']} missing reply A")
        check(bool(l["reply_draft_b"]), f"{l['tweet_id']} missing reply B")
        check(bool(l["dm_draft"]), f"{l['tweet_id']} missing DM")
        check(len(l.get("styles_used") or []) == 2, f"{l['tweet_id']} not 2 styles")
        for d in (l["reply_draft_a"], l["reply_draft_b"]):
            check("—" not in d, f"{l['tweet_id']} draft has em-dash")
            check("http" not in d.lower(), f"{l['tweet_id']} draft has link")
            check(len(d) <= settings["drafting"]["max_reply_chars"], f"{l['tweet_id']} draft too long")

    # style rotation: no two consecutive delivered leads share a style
    seqs = [tuple(l.get("styles_used") or []) for l in delivered]
    for a, b in zip(seqs, seqs[1:]):
        check(not (set(a) & set(b)), f"consecutive leads reused a style: {a} & {b}")

    # DEDUP: second run over same DB should deliver nothing new and skip everything
    sink2: list = []
    stats2 = run_pipeline(db, settings, queries, fixture=FIXTURE, dry_run=True, discord_sink=sink2)
    check(stats2["delivered"] == 0, f"second run delivered {stats2['delivered']} (should be 0)")
    check(stats2["seen_skipped"] == stats2["tweets_scraped"], "second run did not skip all as seen")

    # ── report ──
    print("\n" + "=" * 60)
    print(f"RUN 1: {stats1['tweets_scraped']} scraped, {stats1['prefiltered']} prefiltered, "
          f"{stats1['scored']} scored, {stats1['delivered']} delivered, "
          f"{stats1['borderline']} borderline, {stats1['out_of_market']} out-of-market")
    print(f"  drop reasons: {stats1['drop_reasons']}")
    print(f"RUN 2 (dedup): {stats2['tweets_scraped']} scraped, {stats2['seen_skipped']} skipped-seen, "
          f"{stats2['delivered']} delivered")
    print("\nDelivered leads:")
    for l in delivered:
        print(f"  @{l['handle']} [{l['score']}/{l['confidence']}%] styles={l['styles_used']}")
        print(f"     A: {l['reply_draft_a']}")
        print(f"     B: {l['reply_draft_b']}")
    print("=" * 60)

    if failures:
        print(f"\n❌ {len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n✅ ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
