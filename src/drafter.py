"""Style-driven reply + DM drafting.

The quality mechanism: a 20-style library gives the writer model a concrete structure to
imitate per tweet type (a guided model writes far better than "be natural"). Per lead we
pick two eligible styles NOT used in the last N delivered leads, write one draft each, then
a DIFFERENT model family audits both for AI tells and rewrites once if needed.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

import llm
from util import get_logger, load_prompt

log = get_logger("drafter")

# Fallback style pools per type, used only if parsing yields nothing for a type.
_DEFAULT_TYPE = "vent"

_WRITER_SYSTEM = (
    "You write X (Twitter) replies as Usman, a hands-on AI/automation engineer. "
    "You imitate the assigned style's STRUCTURE, never copy its example. You output strict JSON."
)
_CHECKER_SYSTEM = (
    "You are a ruthless editor detecting AI-generated-sounding replies. You output strict JSON."
)
_DM_SYSTEM = "You draft a short, human, non-pitchy follow-up DM. You output strict JSON."


@dataclass
class Style:
    name: str
    types: list[str]
    structure: str
    example: str


def parse_styles(md: str) -> list[Style]:
    styles: list[Style] = []
    blocks = re.split(r"^## STYLE:\s*", md, flags=re.M)[1:]
    for block in blocks:
        lines = block.strip().splitlines()
        name = lines[0].strip()
        types, structure, example = [], "", ""
        for ln in lines[1:]:
            if ln.lower().startswith("types:"):
                types = [t.strip() for t in ln.split(":", 1)[1].split(",") if t.strip()]
            elif ln.lower().startswith("structure:"):
                structure = ln.split(":", 1)[1].strip()
            elif ln.lower().startswith("example:"):
                example = ln.split(":", 1)[1].strip()
        if name:
            styles.append(Style(name, types, structure, example))
    return styles


def select_styles(
    styles: list[Style], tweet_type: str, excluded: set[str], seed: str, n: int = 2
) -> list[Style]:
    """Pick n styles matching tweet_type, preferring ones not recently used.

    Deterministic per-tweet (seeded by tweet id) so re-runs are stable but variety is high
    across different tweets.
    """
    rng = random.Random(seed)
    eligible = [s for s in styles if tweet_type in s.types] or [
        s for s in styles if _DEFAULT_TYPE in s.types
    ] or styles

    fresh = [s for s in eligible if s.name not in excluded]
    pool = fresh if len(fresh) >= n else eligible  # relax exclusion only if forced
    rng.shuffle(pool)
    return pool[:n]


# ── draft hygiene (deterministic, cheap) ──────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.I)
_PITCH_RE = re.compile(r"\b(dm me|book a call|i can build|hire me|check out my|i offer)\b", re.I)


def clean_text(text: str) -> str:
    # Em-dash / spaced en-dash read as AI tells -> comma. Other unicode dashes and
    # non-breaking hyphens (U+2011, common in model output like "15‑hour") -> plain hyphen.
    text = text.replace("—", ", ").replace(" – ", ", ")
    text = text.translate({0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-"})
    text = _URL_RE.sub("", text.strip()).strip()
    return re.sub(r"\s{2,}", " ", text)


def violates_hard_rules(text: str, max_chars: int) -> list[str]:
    issues = []
    if len(text) > max_chars:
        issues.append(f"too_long({len(text)})")
    if _URL_RE.search(text):
        issues.append("contains_link")
    if _PITCH_RE.search(text):
        issues.append("contains_pitch")
    if "—" in text:
        issues.append("em_dash")
    if "?" not in text:
        issues.append("no_question")
    return issues


# ── LLM steps ─────────────────────────────────────────────────────────────────

def _write_drafts(tweet: dict, score: dict, chosen: list[Style], proof: str, settings: dict) -> list[dict]:
    dr = settings["drafting"]
    persona = load_prompt("reply_persona.md").replace("{MAX_CHARS}", str(dr["max_reply_chars"]))
    style_block = "\n".join(
        f"- {s.name}: {s.structure}" for s in chosen
    )
    user = (
        f"{persona}\n\n"
        f"TWEET by @{tweet['handle']}: {tweet['text']}\n"
        f"AUTHOR BIO: {tweet.get('bio') or '(none)'}\n"
        f"TWEET TYPE: {score['tweet_type']}\n"
        f"WRITE ONE DRAFT FOR EACH OF THESE TWO STYLES:\n{style_block}\n\n"
        f"PROOF LIBRARY (only source of any experience claim; use only if genuinely relevant):\n{proof}\n\n"
        f'Return: {{"drafts":[{{"style":"{chosen[0].name}","text":"..."}},'
        f'{{"style":"{chosen[1].name}","text":"..."}}]}}'
    )
    result = llm.call_json(
        _WRITER_SYSTEM, user, model=dr["model"], fallback_model=dr.get("fallback_model"), temperature=0.7
    )
    return result.get("drafts", [])


def _check_and_fix(text: str, max_chars: int, settings: dict) -> str:
    """Run the AI-tell checker (different model family). One rewrite round. Then hard-clean."""
    dr = settings["drafting"]
    user = (
        "Audit this X reply. Flag AI tells: praise-then-restate openers, em-dashes, "
        "listicle cadence, 'as someone who', generic filler, anything that doesn't sound "
        "like a real dev typing fast. It must stay under "
        f"{max_chars} chars, contain no links, no pitch, and end with a question.\n\n"
        f'REPLY: "{text}"\n\n'
        'Return {"pass": bool, "issues": [..], "rewrite": "<improved reply, or empty if pass>"}'
    )
    try:
        verdict = llm.call_json(_CHECKER_SYSTEM, user, model=dr["checker_model"], temperature=0.3)
        if not verdict.get("pass") and verdict.get("rewrite"):
            text = verdict["rewrite"]
    except Exception as e:  # noqa: BLE001 — checker is best-effort; never block a draft on it
        log.warning("AI-tell check failed, keeping original: %s", e)
    return _enforce_length(clean_text(text), max_chars, settings)


def _enforce_length(text: str, max_chars: int, settings: dict) -> str:
    """Guarantee the reply fits max_chars. Try an LLM shorten first (keeps it natural +
    keeps the closing question), then hard-trim at a sentence boundary as a last resort."""
    if len(text) <= max_chars:
        return text
    try:
        user = (
            f"Shorten this X reply to UNDER {max_chars} characters. Keep it natural, keep the "
            f"closing question, drop the least important clause. No links, no em-dashes.\n\n"
            f'REPLY: "{text}"\n\nReturn {{"text": "<shortened reply>"}}'
        )
        out = clean_text(llm.call_json(_CHECKER_SYSTEM, user, model=settings["drafting"]["checker_model"], temperature=0.3).get("text", ""))
        if out and len(out) <= max_chars:
            return out
        if out:
            text = out
    except Exception as e:  # noqa: BLE001
        log.warning("length-shorten failed: %s", e)
    # Last resort: keep whole sentences up to the limit; preserve a trailing question if present.
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    cut = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
    return (clipped[: cut + 1].strip() if cut > 40 else clipped.rsplit(" ", 1)[0].strip())


def _write_dm(tweet: dict, score: dict, proof: str, settings: dict) -> str:
    persona = load_prompt("dm_persona.md")
    user = (
        f"{persona}\n\nCONTEXT — the prospect tweeted: {tweet['text']}\n"
        f"They just replied to Usman's public reply. Draft the follow-up DM.\n"
        f"PROOF (only source of claims): {proof}"
    )
    try:
        return clean_text(llm.call_json(_DM_SYSTEM, user, model=settings["drafting"]["model"], temperature=0.6).get("dm", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("DM draft failed: %s", e)
        return ""


# ── public API ────────────────────────────────────────────────────────────────

_EMAIL_SYSTEM = "You write short, specific, human cold emails. You output strict JSON."


def _draft_email(lead: dict, proof: str, settings: dict) -> dict[str, Any]:
    """HN 'SEEKING FREELANCER' leads are worked by email, not an X reply."""
    persona = load_prompt("email_persona.md")
    user = (
        f"{persona}\n\nTHEIR HACKER NEWS POST:\n{lead['text'][:1200]}\n\n"
        f"PROOF LIBRARY (only source of any experience claim):\n{proof}"
    )
    try:
        out = llm.call_json(_EMAIL_SYSTEM, user, model=settings["drafting"]["model"],
                            fallback_model=settings["drafting"].get("fallback_model"), temperature=0.6)
        subject = clean_text(out.get("subject", ""))
        body = out.get("body", "").replace("—", "-").strip()
        email = f"Subject: {subject}\n\n{body}" if subject else body
    except Exception as e:  # noqa: BLE001
        log.warning("email draft failed: %s", e)
        email = ""
    return {
        "styles_used": ["Cold Email"],
        "reply_draft_a": email,
        "reply_draft_b": "",
        "draft_issues": {},
        "dm_draft": f"contact: {lead.get('contact_email', '')}" if lead.get("contact_email") else "",
    }


def draft_for_lead(
    tweet: dict, settings: dict, styles: list[Style], excluded: set[str], proof: str
) -> dict[str, Any]:
    if tweet.get("source") == "hn":
        return _draft_email(tweet, proof, settings)

    score = tweet["_score"]
    max_chars = settings["drafting"]["max_reply_chars"]
    chosen = select_styles(styles, score["tweet_type"], excluded, seed=tweet["tweet_id"])

    raw = _write_drafts(tweet, score, chosen, proof, settings)
    drafts: list[dict] = []
    for i, style in enumerate(chosen):
        text = raw[i].get("text", "") if i < len(raw) else ""
        if not text:
            continue
        text = _check_and_fix(clean_text(text), max_chars, settings)
        issues = violates_hard_rules(text, max_chars)
        drafts.append({"style": style.name, "text": text, "issues": issues})

    dm = _write_dm(tweet, score, proof, settings)
    return {
        "styles_used": [d["style"] for d in drafts],
        "reply_draft_a": drafts[0]["text"] if len(drafts) > 0 else "",
        "reply_draft_b": drafts[1]["text"] if len(drafts) > 1 else "",
        "draft_issues": {d["style"]: d["issues"] for d in drafts},
        "dm_draft": dm,
    }
