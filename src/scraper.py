"""Apify X/Twitter scraper wrapper.

Actor-agnostic: input building and output normalization are isolated per provider so
swapping actors is a config change (settings.yaml scraper.provider). The normalizer is
deliberately defensive — these actors rename output fields between versions, so we probe
several known aliases for each field rather than trusting one schema.

VERIFY-ON-FIRST-RUN: the exact input field names below (searchTerms/maxItems/sort) match
the kaito and apidojo actors as of the plan date. Run the smoke test in scraper_smoke()
against a live token and confirm the returned item shape before trusting a scheduled run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from dateutil import parser as dateparser  # python-dateutil (see requirements.txt)

from util import collapse_ws, get_logger, now_utc

log = get_logger("scraper")


# ── input building (per provider) ─────────────────────────────────────────────

def _since_operator(freshness_hours: int, last_run: datetime | None) -> str:
    """Return an X `since:` datetime string, capped so we never look past freshness window."""
    floor = now_utc() - timedelta(hours=freshness_hours)
    since = max(last_run, floor) if last_run else floor
    # X search accepts `since:YYYY-MM-DD_HH:MM:SS_UTC`
    return since.astimezone(timezone.utc).strftime("since:%Y-%m-%d_%H:%M:%S_UTC")


def build_actor_input(
    provider: str, queries: list[dict], settings: dict, last_run: datetime | None
) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Return (actor_id, actor_input, term_to_query_id map)."""
    scr = settings["scraper"]
    actor_id = scr["providers"][provider]["actor_id"]
    freshness = scr["freshness_hours"]
    since = _since_operator(freshness, last_run)

    term_map: dict[str, str] = {}
    terms: list[str] = []
    for q in queries:
        term = f'{collapse_ws(q["query"])} {since}'
        terms.append(term)
        term_map[term] = q["id"]

    max_items = min(
        scr["max_items_per_query"] * len(queries), scr["max_total_items_per_run"]
    )

    if provider in ("kaito", "apidojo"):
        actor_input = {
            "searchTerms": terms,
            "maxItems": max_items,
            "sort": "Latest",
            "tweetLanguage": "en",
        }
    else:
        raise ValueError(f"Unknown scraper provider: {provider}")

    return actor_id, actor_input, term_map


# ── output normalization ──────────────────────────────────────────────────────

def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        dt = dateparser.parse(str(value))
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_tweet(raw: dict, query_id: str | None, niche: str | None) -> dict[str, Any] | None:
    """Map a raw actor item to the canonical lead dict. Returns None if unusable."""
    author = _first(raw, "author", "user", default={}) or {}
    tweet_id = str(_first(raw, "id", "id_str", "tweetId", default="") or "")
    text = collapse_ws(_first(raw, "text", "full_text", "fullText", "content", default=""))
    if not tweet_id or not text:
        return None

    handle = _first(author, "userName", "screen_name", "username", "handle", default="") or ""
    created = _parse_dt(_first(raw, "createdAt", "created_at", "date", "timestamp"))
    acct_created = _parse_dt(
        _first(author, "createdAt", "created_at", "joined", "userCreatedAt")
    )
    followers = int(_first(author, "followers", "followersCount", "followers_count", default=0) or 0)
    following = int(_first(author, "following", "followingCount", "friends_count", default=0) or 0)
    statuses = _first(author, "statusesCount", "statuses_count", "tweetsCount", default=None)

    return {
        "tweet_id": tweet_id,
        "text": text,
        "url": _first(raw, "url", "twitterUrl", "tweetUrl", default=f"https://x.com/{handle}/status/{tweet_id}"),
        "created_at": created,
        "author_id": str(_first(author, "id", "id_str", "userId", default="") or ""),
        "handle": handle,
        "author_name": _first(author, "name", "displayName", "fullName", default="") or "",
        "bio": collapse_ws(_first(author, "description", "bio", "rawDescription", default="")),
        "location": collapse_ws(_first(author, "location", "userLocation", default="")),
        "followers": followers,
        "following": following,
        "account_created_at": acct_created,
        "statuses_count": int(statuses) if statuses not in (None, "") else None,
        "is_verified": bool(_first(author, "isVerified", "verified", "isBlueVerified", default=False)),
        "query_id": query_id,
        "niche": niche,
    }


# ── run ───────────────────────────────────────────────────────────────────────

def scrape(
    settings: dict,
    queries: list[dict],
    last_run: datetime | None,
    apify_token: str,
    client_factory=None,
) -> tuple[list[dict[str, Any]], float]:
    """Run the configured actor. Returns (normalized deduped tweets, actual run cost USD)."""
    provider = settings["scraper"]["provider"]
    actor_id, actor_input, term_map = build_actor_input(provider, queries, settings, last_run)
    query_niche = {q["id"]: q.get("niche") for q in queries}

    if client_factory is None:
        from apify_client import ApifyClient  # imported lazily so fixture runs need no dep

        client = ApifyClient(apify_token)
    else:
        client = client_factory(apify_token)

    log.info("running actor %s with %d queries (maxItems=%s)", actor_id, len(queries), actor_input["maxItems"])
    # apify-client v3 returns a Pydantic Run object (attributes, not dict keys).
    run = client.actor(actor_id).call(run_input=actor_input)
    if run is None:
        log.warning("actor run returned None (failed/aborted)")
        return [], 0.0
    dataset_id = run.default_dataset_id
    cost = float(getattr(run, "usage_total_usd", 0.0) or 0.0)

    # The actor tags each item with searchTermIndex -> index into our searchTerms list,
    # which is built in `queries` order, so index i maps to queries[i].
    idx_map = {i: (q["id"], q.get("niche")) for i, q in enumerate(queries)}
    items = client.dataset(dataset_id).iterate_items()
    return normalize_items(items, idx_map, term_map, query_niche), cost


def normalize_items(
    items: Iterable[dict],
    idx_map: dict[int, tuple[str, str]],
    term_map: dict[str, str],
    query_niche: dict[str, str],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in items:
        # Attribute the tweet to the query that surfaced it: prefer searchTermIndex
        # (the actor tags each item with it), fall back to the raw search term string.
        qid, niche = None, None
        idx = raw.get("searchTermIndex")
        if isinstance(idx, int) and idx in idx_map:
            qid, niche = idx_map[idx]
        else:
            term = _first(raw, "searchTerm", "search_term", "query")
            if term and term in term_map:
                qid = term_map[term]
                niche = query_niche.get(qid)
        norm = normalize_tweet(raw, qid, niche)
        if not norm or norm["tweet_id"] in seen:
            continue
        seen.add(norm["tweet_id"])
        out.append(norm)
    log.info("normalized %d unique tweets", len(out))
    return out
