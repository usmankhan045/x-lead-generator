"""Deterministic mock for llm.call_json — used only with --mock-llm.

Lets the whole pipeline be exercised end-to-end (routing, thresholds, style rotation,
Discord embeds, dedup) with zero network and no API keys. Responses are heuristic, keyed
off distinctive phrases in each stage's system prompt. NOT used in scheduled runs.
"""
from __future__ import annotations

import hashlib
import re


def _seed_int(text: str) -> int:
    return int(hashlib.md5(text.encode()).hexdigest(), 16)


def _field(user: str, label: str) -> str:
    m = re.search(rf"^{label}:\s*(.+)$", user, re.M | re.I)
    return m.group(1).strip() if m else ""


def _score_response(user: str) -> dict:
    # Parse only the filled-in fields, NOT the whole prompt (which contains rubric words
    # like "venting" that would otherwise pollute keyword matching).
    tweet = user.split("old):", 1)[1].strip() if "old):" in user else user
    bio = _field(user, "BIO")
    loc = _field(user, "LOCATION").lower()
    text = f"{tweet}\n{bio}".lower()

    # crude country inference for the mock
    country, in_target = None, None
    if any(k in loc for k in ["tx", "usa", "us", "new york", "california", "austin", "london", "uk", "toronto", "sydney", "berlin"]):
        country = "US" if any(k in loc for k in ["tx", "usa", "us", "york", "california", "austin"]) else "GB"
        in_target = True
    if any(k in loc for k in ["india", "delhi", "mumbai", "bangalore", "lahore", "karachi", "lagos"]):
        country, in_target = "IN", False

    # score from intent signals
    score = 45
    if any(k in text for k in ["waste", "hours", "manually", "nightmare", "sick of", "spend hours"]):
        score += 20
    if any(k in text for k in ["is there a tool", "recommend", "looking for", "need someone", "how much", "anyone build"]):
        score += 18
    if any(k in text for k in ["founder", "ceo", "owner", "my store", "my clients", "realtor", "coach"]):
        score += 12
    score = min(score + (_seed_int(user) % 8), 100)

    tw = tweet.lower()
    if "how much" in tw or "cost to build" in tw or "budget" in tw:
        ttype = "cost-ask"
    elif "looking for a developer" in tw or "need someone to build" in tw or "who can build" in tw or "can anyone build" in tw:
        ttype = "hire-ask"
    elif "is there a tool" in tw or "is there an app" in tw or "recommend" in tw or "app that" in tw:
        ttype = "tool-rec-ask"
    elif "automate" in tw or "better way" in tw or "should be automated" in tw:
        ttype = "automation-doubt"
    elif "sick of" in tw or "tired of" in tw or "killing me" in tw or "hours" in tw:
        ttype = "vent"
    else:
        ttype = "question-ask"

    confidence = 60
    if loc and country:
        confidence += 20
    if "founder" in text or "owner" in text:
        confidence += 10
    confidence = min(confidence, 100)

    return {
        "score": score,
        "subscores": {"pain": 18, "authority": 15, "fit": 15, "urgency": 10, "market": 15 if in_target else 5},
        "red_flags": [],
        "confidence": confidence,
        "confidence_reasons": ["mock heuristic"],
        "tweet_type": ttype,
        "niche": "automation",
        "market": {"country": country, "in_target": in_target, "basis": f"loc='{loc}'"},
        "reasoning": f"mock score {score} for {ttype}",
    }


def _draft_response(user: str) -> dict:
    styles = re.findall(r"^- (.+?):", user, re.M)
    styles = styles[:2] if styles else ["Diagnostic Probe", "Mini Blueprint"]
    return {
        "drafts": [
            {"style": styles[0], "text": "curious what tool youre wrestling with here, whats the actual bottleneck, the export or the re-entry?"},
            {"style": styles[1] if len(styles) > 1 else styles[0], "text": "webhook into a small script beats the native connector for this every time. whats on the receiving end?"},
        ]
    }


def call_json(system: str, user: str, model: str, fallback_model=None, temperature: float = 0.4) -> dict:
    s = system.lower()
    if "lead-qualification" in s:
        return _score_response(user)
    if "write x" in s or "twitter) replies" in s:
        return _draft_response(user)
    if "editor detecting" in s:
        return {"pass": True, "issues": [], "rewrite": ""}
    if "follow-up dm" in s:
        return {"dm": "saw your tweet about the manual re-entry. happy to sketch how id wire it if useful, want me to send it over?"}
    return {}
