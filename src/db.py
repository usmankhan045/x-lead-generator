"""Persistence layer.

Two backends behind one interface:
  - SupabaseDB: real, used in scheduled runs
  - MemoryDB:   in-memory, used by --dry-run / --fixture so tests touch no network and
                the never-scan-twice logic can still be exercised within a process

Both expose the same methods so main.py is backend-agnostic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from util import get_logger, now_utc

log = get_logger("db")

# Columns that exist on x_leads — used to strip transient fields before insert.
_LEAD_COLUMNS = {
    "tweet_id", "author_id", "handle", "author_name", "text", "bio", "location",
    "followers", "tweet_url", "niche", "tweet_type", "query_id", "score", "confidence",
    "score_json", "styles_used", "reply_draft_a", "reply_draft_b", "dm_draft",
    "status", "tweet_created_at", "created_at",
}


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone().isoformat() if dt else None


class MemoryDB:
    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.leads: list[dict] = []
        self.runs: list[dict] = []

    def last_run_started_at(self) -> datetime | None:
        return None  # fixture runs always use the freshness floor

    def filter_unseen(self, ids: list[str]) -> set[str]:
        return {i for i in ids if i not in self.seen}

    def mark_seen(self, tweet_ids: list[str], run_id: str) -> None:
        self.seen.update(tweet_ids)

    def recent_delivered_styles(self, n_leads: int) -> list[str]:
        delivered = [l for l in self.leads if l.get("status") == "delivered"]
        styles: list[str] = []
        for lead in delivered[-n_leads:]:
            styles.extend(lead.get("styles_used") or [])
        return styles

    def insert_lead(self, lead: dict) -> None:
        self.leads.append(lead)

    def create_run(self, run_id: str) -> None:
        self.runs.append({"run_id": run_id, "started_at": now_utc()})

    def finish_run(self, run_id: str, stats: dict) -> None:
        for r in self.runs:
            if r["run_id"] == run_id:
                r.update(stats)


class SupabaseDB:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        url = (url or "").strip()
        key = (key or "").strip()
        if not url.startswith(("http://", "https://")):
            raise RuntimeError(
                f"SUPABASE_URL looks malformed ({url[:40]!r}). It must be the full project URL "
                "like https://<ref>.supabase.co with no quotes/spaces/newline. "
                "Check the GitHub Actions secret."
            )
        self.client = create_client(url, key)

    def last_run_started_at(self) -> datetime | None:
        res = (
            self.client.table("x_runs")
            .select("started_at")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            from dateutil import parser as dateparser

            return dateparser.parse(res.data[0]["started_at"])
        return None

    def filter_unseen(self, ids: list[str]) -> set[str]:
        """Return the subset of ids NOT already in x_seen_tweets."""
        if not ids:
            return set()
        seen: set[str] = set()
        # chunk to keep the `in` list well under any URL length limit
        for i in range(0, len(ids), 200):
            chunk = ids[i : i + 200]
            res = self.client.table("x_seen_tweets").select("tweet_id").in_("tweet_id", chunk).execute()
            seen.update(row["tweet_id"] for row in res.data)
        return {i for i in ids if i not in seen}

    def mark_seen(self, tweet_ids: list[str], run_id: str) -> None:
        if not tweet_ids:
            return
        rows = [{"tweet_id": tid, "first_seen_run": run_id} for tid in tweet_ids]
        self.client.table("x_seen_tweets").upsert(rows, on_conflict="tweet_id").execute()

    def recent_delivered_styles(self, n_leads: int) -> list[str]:
        res = (
            self.client.table("x_leads")
            .select("styles_used")
            .eq("status", "delivered")
            .order("created_at", desc=True)
            .limit(n_leads)
            .execute()
        )
        styles: list[str] = []
        for row in res.data:
            if row.get("styles_used"):
                styles.extend(row["styles_used"])
        return styles

    def insert_lead(self, lead: dict) -> None:
        row = {k: v for k, v in lead.items() if k in _LEAD_COLUMNS}
        self.client.table("x_leads").upsert(row, on_conflict="tweet_id").execute()

    def create_run(self, run_id: str) -> None:
        self.client.table("x_runs").insert({"run_id": run_id}).execute()

    def finish_run(self, run_id: str, stats: dict) -> None:
        stats = {**stats, "finished_at": _iso(now_utc())}
        self.client.table("x_runs").update(stats).eq("run_id", run_id).execute()


def make_db(dry_run: bool, url: str | None, key: str | None):
    if dry_run or not (url and key):
        log.info("using in-memory DB (dry-run or missing Supabase creds)")
        return MemoryDB()
    return SupabaseDB(url, key)
