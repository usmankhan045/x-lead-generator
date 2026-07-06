"""Offline test for the Hacker News source path: parsing, source-aware prefilter,
email drafting, and a source-aware Discord card. No network (mock LLM + synthetic comment)."""
from __future__ import annotations

import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import discord_notify  # noqa: E402
import drafter  # noqa: E402
import hn  # noqa: E402
import llm  # noqa: E402
import mock_llm  # noqa: E402
import prefilter  # noqa: E402
import scorer  # noqa: E402
from util import load_prompt, load_settings, now_utc  # noqa: E402


def main() -> int:
    llm.set_mock(mock_llm.call_json)
    settings = load_settings()
    failures: list[str] = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    # synthetic HN "SEEKING FREELANCER" comment (recent), as the Algolia items API returns
    now_i = int(now_utc().timestamp())
    comment = {
        "id": 44444444,
        "author": "acme_founder",
        "created_at_i": now_i - 3600,
        "text": "SEEKING FREELANCER | Remote | We're a Shopify store and need someone to build an "
                "automation that syncs inventory across 3 channels. Python/n8n ideal. Email jobs@acme.co",
    }
    text = hn._strip_html(comment["text"])
    lead = hn._normalize(comment, text)

    check(lead["source"] == "hn", "source not hn")
    check(lead["tweet_id"] == "hn-44444444", f"bad id {lead['tweet_id']}")
    check(lead["location"] == "Remote", f"location parse: {lead['location']!r}")
    check(lead["contact_email"] == "jobs@acme.co", f"email parse: {lead['contact_email']!r}")
    check(lead["niche"] == "ecommerce", f"niche: {lead['niche']}")
    check("news.ycombinator.com/item?id=44444444" in lead["url"], "bad url")

    # source-aware prefilter: HN lead must survive despite no bio/followers
    survivors, drops = prefilter.run([lead], settings, set())
    check(len(survivors) == 1, f"HN lead dropped by prefilter: {drops}")

    # scoring works (mock)
    s = scorer.score_tweet(lead, settings)
    lead["_score"] = s
    check(isinstance(s["score"], int), "no score")

    # drafting produces a cold email, not an X reply
    d = drafter.draft_for_lead(lead, settings, [], set(), load_prompt("proof_library.md"))
    lead.update(d)
    check(d["styles_used"] == ["Cold Email"], f"styles: {d['styles_used']}")
    check("Subject:" in d["reply_draft_a"], "email has no subject")
    check(d["reply_draft_b"] == "", "HN lead should have no reply B")

    # source-aware Discord card
    lead["_age_hours"] = 1
    embed = discord_notify.build_lead_embed(lead, 1, 1, tier="LEAD")
    names = [f["name"] for f in embed["fields"]]
    check(any("Open the HN post" in n for n in names), "no HN-post link label")
    check(any("COLD EMAIL" in n for n in names), "no cold-email field")
    check(any("Email them at" in n for n in names), "no contact-email field")
    check("Hacker News" in embed["description"], "card doesn't mark HN source")

    print("\n=== HN lead card preview ===")
    print("title:", embed["title"])
    for f in embed["fields"]:
        print(f"  {f['name']}: {f['value'][:80]}")

    if failures:
        print(f"\n❌ {len(failures)} FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("\n✅ HN SOURCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
