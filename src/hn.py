"""Hacker News lead source — the monthly "Freelancer? Seeking freelancer?" thread.

Comments there come in two flavours: "SEEKING WORK" (freelancers offering themselves) and
"SEEKING FREELANCER" (companies who want to hire, usually with an email). We keep only the
SEEKING FREELANCER ones — those are buyers. Read-only via the free Algolia HN API (no auth,
no account, nothing to ban); outreach is a cold email, drafted downstream.

Normalized output matches the tweet lead dict so it flows through the same pipeline, with
source="hn" so prefilter/scorer/drafter/Discord treat it appropriately.
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


def _strip_html(s: str | None) -> str:
    s = html.unescape(s or "")
    s = s.replace("<p>", "\n").replace("</p>", " ")
    s = re.sub(r"<[^>]+>", " ", s)
    return collapse_ws(s)


def _find_freelancer_thread() -> str | None:
    """Return the objectID of the most recent 'Freelancer? Seeking freelancer?' story."""
    try:
        r = requests.get(
            f"{ALGOLIA}/search_by_date",
            params={"query": "Freelancer Seeking freelancer", "tags": "story,author_whoishiring", "hitsPerPage": 10},
            timeout=20,
        )
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            title = (hit.get("title") or "").lower()
            if "freelancer" in title and "seeking" in title:
                return hit["objectID"]
    except requests.RequestException as e:
        log.warning("HN thread search failed: %s", e)
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


def _normalize(comment: dict, text: str) -> dict[str, Any]:
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
        "query_id": "hn-seeking-freelancer",
        "niche": _infer_niche(text),
        "contact_email": email.group(0) if email else "",
    }


def fetch_leads(settings: dict, last_run: datetime | None) -> tuple[list[dict[str, Any]], float]:
    """Return (normalized SEEKING FREELANCER leads within the lookback window, cost=0.0)."""
    cfg = settings.get("sources", {}).get("hackernews", {})
    lookback_h = cfg.get("freshness_hours", 336)
    max_items = cfg.get("max_items", 40)
    floor = now_utc() - timedelta(hours=lookback_h)
    if last_run:
        floor = max(floor, last_run)

    story_id = _find_freelancer_thread()
    if not story_id:
        log.warning("no HN freelancer thread found")
        return [], 0.0

    try:
        item = requests.get(f"{ALGOLIA}/items/{story_id}", timeout=30).json()
    except requests.RequestException as e:
        log.warning("HN item fetch failed: %s", e)
        return [], 0.0

    out: list[dict] = []
    for c in item.get("children") or []:
        if not c or not c.get("text") or not c.get("created_at_i"):
            continue
        text = _strip_html(c["text"])
        # keep only companies hiring (SEEKING FREELANCER), skip freelancers offering (SEEKING WORK)
        if "seeking freelancer" not in text[:60].lower():
            continue
        created = datetime.fromtimestamp(c["created_at_i"], tz=timezone.utc)
        if created < floor:
            continue
        out.append(_normalize(c, text))
        if len(out) >= max_items:
            break

    log.info("HN: %d SEEKING FREELANCER leads within %dh", len(out), lookback_h)
    return out, 0.0
