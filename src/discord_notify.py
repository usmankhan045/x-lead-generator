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

# Confidence bands -> embed color (green/yellow/red), label, and emoji dot.
_BANDS = [
    (80, 0x2ECC71, "High", "🟢"),
    (55, 0xF1C40F, "Medium", "🟡"),
    (0, 0xE74C3C, "Low", "🔴"),
]


def _band(confidence: int) -> tuple[int, str, str]:
    for threshold, color, label, emoji in _BANDS:
        if confidence >= threshold:
            return color, label, emoji
    return 0x95A5A6, "Low", "🔴"


def _trunc(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def build_lead_embed(lead: dict, index: int, total: int, tier: str = "LEAD") -> dict[str, Any]:
    """One self-contained card per lead: header, their post + link, then the answers.

    tier "LEAD"   -> 🎯 high-confidence, act on these (main channel)
    tier "REVIEW" -> 🔎 mid-tier, your judgment (review channel)

    Layout (top to bottom):
      title  : 🎯 Lead 2/3 · @handle          (clickable -> opens the tweet)
      desc   : score/confidence · author meta · their tweet (quoted) · open-link · why
      fields : ✍️ REPLY A, ✍️ REPLY B, 📩 DM   (each a copy-paste code block)
    """
    score = lead["_score"]
    conf = score["confidence"]
    color, band, dot = _band(conf)
    label, icon = ("Review", "🔎") if tier == "REVIEW" else ("Lead", "🎯")
    age_h = lead.get("_age_hours")
    age_str = f"{age_h:.0f}h old" if isinstance(age_h, (int, float)) and age_h >= 0 else "age unknown"

    market = score["market"]
    loc = market.get("country") or "?"
    loc_flag = " ⚠️ location unknown" if market.get("in_target") is None else ""
    url = lead.get("url", "")

    # Description: everything ABOUT the lead (not the answers), clearly bounded.
    desc = (
        f"**Score {score['score']}/100 · {dot} {conf}% confidence** · {lead.get('niche', '')} · {age_str}\n"
        f"👤 **@{lead.get('handle', '')}** · {lead.get('followers', 0):,} followers · {loc}{loc_flag}\n\n"
        f"💬 **Their post:**\n>>> {_trunc(lead['text'], 600)}"
    )
    reason = score.get("reasoning", "")
    footer_flags = [f"{s}: {', '.join(iss)}" for s, iss in (lead.get("draft_issues") or {}).items() if iss]

    # Fields: ONLY the answers, each clearly labeled and in its own copy-paste block.
    styles = lead.get("styles_used") or []
    fields = [{"name": "🔗 Open the tweet", "value": url or "—", "inline": False}]
    if reason:
        fields.append({"name": "🧠 Why it's a lead", "value": _trunc(reason, 300), "inline": False})
    if lead.get("reply_draft_a"):
        fields.append({"name": f"✍️ REPLY — option A ({styles[0] if styles else '—'})",
                       "value": f"```{_trunc(lead['reply_draft_a'], 480)}```", "inline": False})
    if lead.get("reply_draft_b"):
        fields.append({"name": f"✍️ REPLY — option B ({styles[1] if len(styles) > 1 else '—'})",
                       "value": f"```{_trunc(lead['reply_draft_b'], 480)}```", "inline": False})
    if lead.get("dm_draft"):
        fields.append({"name": "📩 DM — send ONLY after they reply to you",
                       "value": f"```{_trunc(lead['dm_draft'], 480)}```", "inline": False})

    footer = f"{label.lower()} {index}/{total} · query: {lead.get('query_id', '?')}"
    if footer_flags:
        footer += " · ⚠️ " + _trunc("; ".join(footer_flags), 120)

    return {
        "title": f"{icon} {label} {index}/{total} · @{lead.get('handle', '')}",
        "url": url,
        "color": color,
        "description": _trunc(desc, 4000),
        "fields": fields,
        "footer": {"text": _trunc(footer, 2040)},
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


def deliver_leads(
    webhook: str, leads: list[dict], dry_run_sink: list | None = None, tier: str = "LEAD"
) -> None:
    """Post one self-contained card per lead, oldest first so the freshest lands at the
    bottom (most visible). Numbered 1..N and separated so leads never blend together."""
    if not leads or not (webhook or dry_run_sink is not None):
        return
    ordered = sorted(leads, key=lambda l: l.get("_age_hours", 0), reverse=True)
    total = len(ordered)
    for i, lead in enumerate(ordered, start=1):
        _post(webhook, {"embeds": [build_lead_embed(lead, i, total, tier)]}, dry_run_sink)
        if dry_run_sink is None:
            time.sleep(0.6)  # stay well under Discord's ~5 req/2s webhook limit
    log.info("delivered %d %s cards", total, tier.lower())


def deliver_digest(
    webhook: str, run_id: str, stats: dict, borderline: list[dict], dry_run_sink: list | None = None
) -> None:
    lines = [
        f"**X lead run `{run_id}`**",
        f"scraped {stats.get('tweets_scraped', 0)} · "
        f"skipped-seen {stats.get('seen_skipped', 0)} · "
        f"prefiltered→{stats.get('prefiltered', 0)} · "
        f"scored {stats.get('scored', 0)} · "
        f"**delivered {stats.get('delivered', 0)}** (main) · "
        f"review {stats.get('borderline', 0)} (review channel)",
        f"est. Apify cost: ${stats.get('est_cost_usd', 0):.3f}",
    ]
    qs = stats.get("query_stats") or {}
    if qs:
        top = sorted(qs.items(), key=lambda kv: kv[1].get("delivered", 0), reverse=True)
        lines.append("**per-query (delivered/scraped):** " + " · ".join(
            f"{qid}({v.get('delivered',0)}/{v.get('scraped',0)})" for qid, v in top
        ))
    if borderline:
        lines.append(f"**{len(borderline)} review-tier lead(s) posted to the review channel** with drafts.")

    _post(webhook, {"content": _trunc("\n".join(lines), 1900)}, dry_run_sink)
    log.info("delivered digest for run %s", run_id)
