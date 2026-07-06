"""Hacker News lead source — the monthly "Who is hiring?" and "Seeking freelancer?" threads.

Two threads, both posted monthly by @whoishiring:
  - "Ask HN: Who is hiring?" — reliable, ~200+ posts/month. We keep only the CONTRACT/FREELANCE
    -friendly ones (companies open to non-employee work = real clients for a freelancer).
  - "Ask HN: Freelancer? Seeking freelancer?" — when it exists, keep the SEEKING FREELANCER
    posts (companies wanting to hire). Often sparse.

Read-only via the free Algolia HN API (no auth, no account, nothing to ban); outreach is a
cold email, drafted downstream. The scorer's fit-gate then keeps only roles matching Usman's
services (AI/automation/app/web/dev) and drops the rest (embedded Rust, sales, etc.).

Normalized output matches the tweet lead dict (source="hn") so it flows through the pipeline.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from util import collapse_ws, get_logger, now_utc

log = get_logger("hn")

ALGOLIA = "https://hn.algolia.com/api/v1"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LOC_RE = re.compile(r"(?:location|based in|located)[:\s]+([A-Za-z .,'/-]{2,40})", re.I)
_REMOTE_RE = re.compile(r"\bremote\b", re.I)
# contract/freelance-friendly signal (word-boundary) in a Who-is-hiring post header
_CONTRACT_RE = re.compile(
    r"\b(contract|contractor|freelance|freelancer|part[- ]?time|1099|c2c|corp[- ]to[- ]corp|project[- ]based)\b",
    re.I,
)


def _strip_html(s: str | None) -> str:
    s = html.unescape(s or "")
    s = s.replace("<p>", "\n").replace("</p>", " ")
    s = re.sub(r"<[^>]+>", " ", s)
    return collapse_ws(s)


def _latest_thread(query: str, must_contain: tuple[str, ...]) -> str | None:
    """Return the objectID of the most recent @whoishiring story whose title matches."""
    try:
        r = requests.get(
            f"{ALGOLIA}/search_by_date",
            params={"query": query, "tags": "story,author_whoishiring", "hitsPerPage": 10},
            timeout=20,
        )
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            title = (hit.get("title") or "").lower()
            if all(w in title for w in must_contain):
                return hit["objectID"]
    except requests.RequestException as e:
        log.warning("HN thread search failed (%s): %s", query, e)
    return None


def _parse_location(text: str) -> str:
    m = _LOC_RE.search(text)
    if m:
        return m.group(1).strip(" .,")
    if _REMOTE_RE.search(text[:200]):
        return "Remote"
    return ""


def _infer_niche(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("shopify", "ecommerce", "e-commerce", "woocommerce", "store")):
        return "ecommerce"
    if any(k in t for k in ("automation", "workflow", "scrap", "integration", "pipeline", "ai agent", "llm", "rag")):
        return "automation"
    return "app-web"


def _normalize(comment: dict, text: str, query_id: str) -> dict[str, Any]:
    cid = str(comment.get("id"))
    author = comment.get("author") or ""
    created = datetime.fromtimestamp(comment["created_at_i"], tz=timezone.utc)
    email = _EMAIL_RE.search(text)
    return {
        "tweet_id": f"hn-{cid}",
        "source": "hn",
        "text": text,
        "url": f"https://news.ycombinator.com/item?id={cid}",
        "created_at": created,
        "author_id": author,
        "handle": author,
        "author_name": author,
        "bio": "",
        "location": _parse_location(text),
        "followers": None,
        "following": None,
        "account_created_at": None,
        "statuses_count": None,
        "is_verified": False,
        "query_id": query_id,
        "niche": _infer_niche(text),
        "contact_email": email.group(0) if email else "",
    }


def _harvest(story_id: str, keep, query_id: str, floor: datetime, out: dict) -> None:
    """Add matching comments from a thread to `out` (keyed by tweet_id, deduped)."""
    try:
        item = requests.get(f"{ALGOLIA}/items/{story_id}", timeout=30).json()
    except requests.RequestException as e:
        log.warning("HN item fetch failed (%s): %s", story_id, e)
        return
    for c in item.get("children") or []:
        if not c or not c.get("text") or not c.get("created_at_i"):
            continue
        text = _strip_html(c["text"])
        if not keep(text):
            continue
        if datetime.fromtimestamp(c["created_at_i"], tz=timezone.utc) < floor:
            continue
        lead = _normalize(c, text, query_id)
        out.setdefault(lead["tweet_id"], lead)


def fetch_leads(settings: dict, last_run: datetime | None) -> tuple[list[dict[str, Any]], float]:
    """Return (normalized HN leads within the lookback window, cost=0.0).

    Always scans the full lookback (HN is free + posts are sparse/long-lived); dedup is handled
    downstream by the seen-table, so we do NOT clamp to last_run like X does.
    """
    cfg = settings.get("sources", {}).get("hackernews", {})
    lookback_h = cfg.get("freshness_hours", 960)
    max_items = cfg.get("max_items", 40)
    floor = now_utc() - timedelta(hours=lookback_h)
    out: dict[str, dict] = {}

    # 1. "Who is hiring?" — reliable monthly, keep contract/freelance-friendly roles only.
    hiring = _latest_thread("Who is hiring", ("who is hiring",))
    if hiring:
        _harvest(hiring, lambda t: bool(_CONTRACT_RE.search(t[:400])), "hn-who-is-hiring", floor, out)

    # 2. "Freelancer? Seeking freelancer?" — bonus, keep SEEKING FREELANCER (companies) posts.
    freelancer = _latest_thread("Freelancer Seeking freelancer", ("freelancer", "seeking"))
    if freelancer:
        _harvest(freelancer, lambda t: "seeking freelancer" in t[:60].lower(),
                 "hn-seeking-freelancer", floor, out)

    leads = list(out.values())[:max_items]
    log.info("HN: %d contract/freelance leads within %dh", len(leads), lookback_h)
    return leads, 0.0
