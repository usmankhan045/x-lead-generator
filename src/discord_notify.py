"""Discord delivery via webhook (no hosted bot — Actions posts and exits).

One rich embed per delivered lead (tweet, author, score + confidence, both style-labeled
reply drafts, DM draft) plus a compact end-of-run digest with per-query stats and the
borderline list.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from util import get_logger

log = get_logger("discord")

# Confidence bands -> embed color (green/yellow/red) and label.
_BANDS = [
    (80, 0x2ECC71, "High"),
    (55, 0xF1C40F, "Medium"),
    (0, 0xE74C3C, "Low"),
]


def _band(confidence: int) -> tuple[int, str]:
    for threshold, color, label in _BANDS:
        if confidence >= threshold:
            return color, label
    return 0x95A5A6, "Low"


def _trunc(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def build_lead_embed(lead: dict) -> dict[str, Any]:
    score = lead["_score"]
    conf = score["confidence"]
    color, band = _band(conf)
    age_h = lead.get("_age_hours")
    age_str = f"{age_h:.0f}h ago" if isinstance(age_h, (int, float)) and age_h >= 0 else "age unknown"

    market = score["market"]
    loc = market.get("country") or "?"
    loc_flag = " ⚠ location unknown" if market.get("in_target") is None else ""

    fields = [
        {
            "name": f"Score {score['score']} · Confidence {conf}% ({band})",
            "value": _trunc(score.get("reasoning", ""), 300) or "—",
            "inline": False,
        },
        {
            "name": f"Author · {lead.get('followers', 0):,} followers · {loc}{loc_flag}",
            "value": _trunc(lead.get("bio") or "(no bio)", 200),
            "inline": False,
        },
    ]

    styles = lead.get("styles_used") or []
    a = lead.get("reply_draft_a")
    b = lead.get("reply_draft_b")
    if a:
        fields.append({"name": f"Reply A · {styles[0] if styles else ''}", "value": f"```{_trunc(a, 480)}```", "inline": False})
    if b:
        fields.append({"name": f"Reply B · {styles[1] if len(styles) > 1 else ''}", "value": f"```{_trunc(b, 480)}```", "inline": False})
    if lead.get("dm_draft"):
        fields.append({"name": "DM (after they reply)", "value": f"```{_trunc(lead['dm_draft'], 480)}```", "inline": False})

    flagged = [f"{s}: {', '.join(iss)}" for s, iss in (lead.get("draft_issues") or {}).items() if iss]
    if flagged:
        fields.append({"name": "⚠ draft flags", "value": _trunc("; ".join(flagged), 200), "inline": False})

    return {
        "title": _trunc(lead["text"], 240),
        "url": lead.get("url"),
        "color": color,
        "author": {"name": f"@{lead.get('handle', '')} · {lead.get('niche', '')} · {age_str}"},
        "fields": fields,
        "footer": {"text": f"query: {lead.get('query_id', '?')}"},
    }


def _post(webhook: str, payload: dict, dry_run_sink: list | None) -> None:
    if dry_run_sink is not None:
        dry_run_sink.append(payload)
        return
    for attempt in range(3):
        resp = requests.post(webhook, json=payload, timeout=15)
        if resp.status_code == 429:  # Discord rate limit
            retry = resp.json().get("retry_after", 1)
            time.sleep(float(retry) + 0.5)
            continue
        if resp.status_code >= 400:
            log.warning("discord post %s: %s", resp.status_code, resp.text[:200])
        resp.raise_for_status()
        return


def deliver_leads(webhook: str, leads: list[dict], dry_run_sink: list | None = None) -> None:
    """Post one message per lead, oldest first so the freshest lands at the bottom (most visible)."""
    ordered = sorted(leads, key=lambda l: l.get("_age_hours", 0), reverse=True)
    for lead in ordered:
        _post(webhook, {"embeds": [build_lead_embed(lead)]}, dry_run_sink)
        if dry_run_sink is None:
            time.sleep(0.6)  # stay well under Discord's ~5 req/2s webhook limit
    log.info("delivered %d leads", len(ordered))


def deliver_digest(
    webhook: str, run_id: str, stats: dict, borderline: list[dict], dry_run_sink: list | None = None
) -> None:
    lines = [
        f"**X lead run `{run_id}`**",
        f"scraped {stats.get('tweets_scraped', 0)} · "
        f"skipped-seen {stats.get('seen_skipped', 0)} · "
        f"prefiltered→{stats.get('prefiltered', 0)} · "
        f"scored {stats.get('scored', 0)} · "
        f"**delivered {stats.get('delivered', 0)}** · "
        f"borderline {stats.get('borderline', 0)}",
        f"est. Apify cost: ${stats.get('est_cost_usd', 0):.3f}",
    ]
    qs = stats.get("query_stats") or {}
    if qs:
        top = sorted(qs.items(), key=lambda kv: kv[1].get("delivered", 0), reverse=True)
        lines.append("**per-query:** " + " · ".join(
            f"{qid}({v.get('delivered',0)}/{v.get('scraped',0)})" for qid, v in top
        ))
    if borderline:
        lines.append("**borderline (50-69), no drafts:**")
        for b in borderline[:10]:
            s = b["_score"]
            lines.append(f"• [{s['score']}/{s['confidence']}%] @{b.get('handle','')}: {_trunc(b['text'], 120)} — <{b.get('url','')}>")

    _post(webhook, {"content": _trunc("\n".join(lines), 1900)}, dry_run_sink)
    log.info("delivered digest for run %s", run_id)
