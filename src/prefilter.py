"""Stage-A pre-filter: free Python rules that drop junk before any LLM call.

Order matters — the two HARD rules (freshness, already-seen) run first and are the
guarantees the user asked for: nothing older than the freshness window is ever processed,
and nothing is ever scored twice.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from util import get_logger, now_utc

log = get_logger("prefilter")

# Negative keywords that didn't fit inside the search query (applied to text + bio).
# Kept lowercase; matched as whole-ish tokens to avoid false hits (e.g. "eth" in "method").
NEGATIVE_KEYWORDS = [
    "crypto", "bitcoin", "btc", "ethereum", "web3", "nft", "airdrop", "presale",
    "memecoin", "degen", "whitelist", "forex", "betting", "casino", "onlyfans",
    "cash app", "cashapp", "telegram", "whatsapp me", "dm for promo", "promo",
    "giveaway", "tag a friend", "retweet to win", "follow and rt", "sweepstakes",
]
_NEG_PATTERNS = [re.compile(rf"(?<!\w){re.escape(k)}(?!\w)", re.I) for k in NEGATIVE_KEYWORDS]

BIO_SPAM_HINTS = ["t.me/", "telegram", "onlyfans", "promo", "crypto", "forex", "🔞"]

# Service-provider / competitor bios. These accounts SELL the exact services Usman does,
# so they're never buyers — they flood "need a website / need a developer" searches with
# their own pitches. Dropping them on the bio (cheap) before the LLM saves scoring calls,
# rate-limit pressure, and noise. Phrases chosen to almost never appear in a real buyer's bio.
COMPETITOR_BIO = [
    "web developer", "web designer", "web design", "app developer", "software developer",
    "full stack", "fullstack", "full-stack", "frontend developer", "backend developer",
    "wordpress developer", "shopify developer", "shopify expert", "webflow developer",
    "i build websites", "i build apps", "i build web", "i create websites", "we build websites",
    "i design websites", "i make websites", "building websites for", "websites that convert",
    "digital agency", "web agency", "design agency", "dev agency", "software house", "software agency",
    "freelance developer", "freelance web", "freelance app", "freelance designer",
    "available for hire", "available for freelance", "available for work", "open for work",
    "open to work", "hire me", "dm for a website", "dms open for", "let's build your",
    "n8n expert", "automation expert", "automation agency", "ai automation agency", "ai agency",
    "i help businesses automate", "i help founders", "we help you automate", "i help you automate",
    "we help businesses grow", "i build ai agents", "we build ai", "no-code developer", "nocode developer",
    # marketer / content-seller signals (seen flooding live results)
    "we help businesses", "we help brands", "we help founders", "helping businesses", "helping brands",
    "helping founders scale", "we automate", "done for you", "book a call", "free guide",
    "dm for pricing", "dm to work", "growth agency", "marketing agency", "ai consultant",
    "automation consultant", "grab your free", "get your free", "we build automations",
    "smma", "lead gen agency", "we scale", "founder of an agency", "digital marketer",
]


class Dropped(Exception):
    """Raised internally with a reason; caller records the reason for run stats."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _account_age_days(tweet: dict) -> float | None:
    created = tweet.get("account_created_at")
    if not created:
        return None
    return (now_utc() - created).total_seconds() / 86400.0


def _posts_per_day(tweet: dict) -> float | None:
    statuses = tweet.get("statuses_count")
    age = _account_age_days(tweet)
    if not statuses or not age or age < 1:
        return None
    return statuses / age


def _freshness_hours(tweet: dict, settings: dict) -> int:
    """Per-source freshness — a HN hiring post stays valid far longer than a tweet."""
    src = tweet.get("source", "x")
    if src == "hn":
        return settings.get("sources", {}).get("hackernews", {}).get("freshness_hours", 336)
    return settings["scraper"]["freshness_hours"]


def check(tweet: dict, settings: dict, seen_ids: set[str], run_text_seen: set[str]) -> None:
    """Raise Dropped(reason) if the tweet should be filtered out. Otherwise return None."""
    pf = settings["prefilter"]
    source = tweet.get("source", "x")

    # HARD RULE 1 — freshness. If created_at is unknown we cannot prove it's fresh -> drop.
    created = tweet.get("created_at")
    if not created:
        raise Dropped("no_timestamp")
    if now_utc() - created > timedelta(hours=_freshness_hours(tweet, settings)):
        raise Dropped("too_old")

    # HARD RULE 2 — never scan twice.
    if tweet["tweet_id"] in seen_ids:
        raise Dropped("already_seen")

    # Duplicate text within this run = copy-paste bot swarm.
    norm_text = tweet["text"].strip().lower()
    if norm_text in run_text_seen:
        raise Dropped("duplicate_text")

    # Negative keywords in text or bio (spam/crypto) — applies to every source.
    haystack = f"{tweet['text']} {tweet.get('bio', '')}"
    for pat in _NEG_PATTERNS:
        if pat.search(haystack):
            raise Dropped(f"neg_kw:{pat.pattern}")

    # The remaining gates are Twitter-author heuristics (bio, followers, account age,
    # post frequency). They don't apply to non-Twitter sources like HN job posts, where
    # there's no follower graph and the buyer signal is in the post text itself.
    if source != "x":
        return

    bio_l = (tweet.get("bio") or "").lower()
    if any(h in bio_l for h in BIO_SPAM_HINTS):
        raise Dropped("bio_spam")

    # Author is a service provider (sells what Usman sells) -> not a buyer.
    if any(c in bio_l for c in COMPETITOR_BIO):
        raise Dropped("competitor_bio")

    # Author quality gates.
    followers = tweet.get("followers") or 0
    if followers < pf["min_followers"]:
        raise Dropped("too_few_followers")
    if followers > pf["max_followers"]:
        raise Dropped("too_many_followers")

    following = tweet.get("following") or 0
    if followers > 0 and following / max(followers, 1) > pf["max_following_ratio"]:
        raise Dropped("bad_follow_ratio")

    age = _account_age_days(tweet)
    if age is not None and age < pf["min_account_age_days"]:
        raise Dropped("account_too_new")

    ppd = _posts_per_day(tweet)
    if ppd is not None and ppd > pf["max_posts_per_day"]:
        raise Dropped("posts_too_frequent")

    if not (tweet.get("bio") or "").strip():
        raise Dropped("empty_bio")


def run(
    tweets: list[dict], settings: dict, seen_ids: set[str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return (survivors, drop_reason_counts)."""
    survivors: list[dict] = []
    reasons: dict[str, int] = {}
    run_text_seen: set[str] = set()
    for t in tweets:
        try:
            check(t, settings, seen_ids, run_text_seen)
        except Dropped as d:
            key = d.reason.split(":")[0]  # collapse neg_kw:<pattern> to neg_kw
            reasons[key] = reasons.get(key, 0) + 1
            continue
        run_text_seen.add(t["text"].strip().lower())
        survivors.append(t)
    log.info("prefilter: %d/%d survived, drops=%s", len(survivors), len(tweets), reasons)
    return survivors, reasons
