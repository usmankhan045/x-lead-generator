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


def check(tweet: dict, settings: dict, seen_ids: set[str], run_text_seen: set[str]) -> None:
    """Raise Dropped(reason) if the tweet should be filtered out. Otherwise return None."""
    pf = settings["prefilter"]
    freshness_hours = settings["scraper"]["freshness_hours"]

    # HARD RULE 1 — freshness. If created_at is unknown we cannot prove it's fresh -> drop.
    created = tweet.get("created_at")
    if not created:
        raise Dropped("no_timestamp")
    if now_utc() - created > timedelta(hours=freshness_hours):
        raise Dropped("too_old")

    # HARD RULE 2 — never scan twice.
    if tweet["tweet_id"] in seen_ids:
        raise Dropped("already_seen")

    # Duplicate text within this run = copy-paste bot swarm.
    norm_text = tweet["text"].strip().lower()
    if norm_text in run_text_seen:
        raise Dropped("duplicate_text")

    # Negative keywords in text or bio.
    haystack = f"{tweet['text']} {tweet.get('bio', '')}"
    for pat in _NEG_PATTERNS:
        if pat.search(haystack):
            raise Dropped(f"neg_kw:{pat.pattern}")

    bio_l = (tweet.get("bio") or "").lower()
    if any(h in bio_l for h in BIO_SPAM_HINTS):
        raise Dropped("bio_spam")

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
