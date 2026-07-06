"""LLM scoring: applies the weighted rubric in prompts/scoring.md to each tweet.

Produces a lead score (0-100), a separate confidence (0-100), a tweet_type used to pick
comment styles, and a market verdict. Tweets confirmed OUTSIDE the target markets are
marked for drop; unknown-location tweets survive with lowered confidence and a flag.
"""
from __future__ import annotations

from typing import Any

import llm
from util import get_logger, load_prompt, now_utc

log = get_logger("scorer")

_SYSTEM = (
    "You are a precise lead-qualification analyst. You output only strict JSON matching the "
    "requested schema. You never invent facts about the author."
)


def _account_age_days(tweet: dict) -> int | None:
    created = tweet.get("account_created_at")
    return int((now_utc() - created).total_seconds() // 86400) if created else None


def _posts_per_day(tweet: dict) -> float | None:
    statuses, age = tweet.get("statuses_count"), _account_age_days(tweet)
    if not statuses or not age or age < 1:
        return None
    return round(statuses / age, 1)


def _tweet_age_hours(tweet: dict) -> float:
    created = tweet.get("created_at")
    return round((now_utc() - created).total_seconds() / 3600.0, 1) if created else -1.0


def build_user_prompt(tweet: dict, target_markets: list[str]) -> str:
    template = load_prompt("scoring.md")
    return (
        template.replace("{TARGET_MARKETS}", ", ".join(target_markets))
        .replace("{handle}", tweet.get("handle", ""))
        .replace("{author_name}", tweet.get("author_name", ""))
        .replace("{bio}", tweet.get("bio") or "(none)")
        .replace("{location}", tweet.get("location") or "(none given)")
        .replace("{followers}", str(tweet.get("followers", 0)))
        .replace("{following}", str(tweet.get("following", 0)))
        .replace("{account_age_days}", str(_account_age_days(tweet) if _account_age_days(tweet) is not None else "unknown"))
        .replace("{posts_per_day}", str(_posts_per_day(tweet) if _posts_per_day(tweet) is not None else "unknown"))
        .replace("{tweet_age_hours}", str(_tweet_age_hours(tweet)))
        .replace("{text}", tweet.get("text", ""))
    )


def score_tweet(tweet: dict, settings: dict) -> dict[str, Any]:
    sc = settings["scoring"]
    markets = settings["markets"]["target"]
    user = build_user_prompt(tweet, markets)
    result = llm.call_json(
        _SYSTEM, user, model=sc["model"], fallback_model=sc.get("fallback_model"), temperature=0.2
    )
    return _normalize_score(result)


def _normalize_score(result: dict) -> dict[str, Any]:
    """Clamp and default fields so downstream code can trust the shape."""
    def clamp(v, lo, hi, default=0):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default

    market = result.get("market") or {}
    return {
        "score": clamp(result.get("score"), 0, 100),
        "subscores": result.get("subscores") or {},
        "red_flags": result.get("red_flags") or [],
        "confidence": clamp(result.get("confidence"), 0, 100),
        "confidence_reasons": result.get("confidence_reasons") or [],
        "tweet_type": result.get("tweet_type") or "vent",
        "niche": result.get("niche") or "other",
        "market": {
            "country": market.get("country"),
            "in_target": market.get("in_target"),
            "basis": market.get("basis", ""),
        },
        "reasoning": result.get("reasoning", ""),
    }


def classify(tweets: list[dict], settings: dict) -> tuple[list[dict], dict[str, int]]:
    """Score each tweet; attach `_score` dict. Drop tweets confirmed outside target markets.

    Returns (kept_tweets, stats). kept_tweets each gain a `_score` key.
    """
    kept: list[dict] = []
    stats = {"scored": 0, "dropped_out_of_market": 0, "errors": 0}
    for t in tweets:
        try:
            s = score_tweet(t, settings)
        except Exception as e:  # noqa: BLE001
            log.warning("scoring failed for %s: %s", t["tweet_id"], e)
            stats["errors"] += 1
            continue
        stats["scored"] += 1
        # Confirmed outside target markets -> drop (in_target is False, not None).
        # Exception: HN contract roles are remote and pay in hard currency regardless of the
        # company's HQ, so don't drop them on location — the fit-gate handles relevance.
        if s["market"]["in_target"] is False and t.get("source") != "hn":
            stats["dropped_out_of_market"] += 1
            continue
        t["_score"] = s
        kept.append(t)
    log.info("scored %d, dropped %d out-of-market, %d errors",
             stats["scored"], stats["dropped_out_of_market"], stats["errors"])
    return kept, stats
