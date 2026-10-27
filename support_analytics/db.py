"""SQLite schema and idempotent ingestion.

Sync is an upsert: re-running it never duplicates rows, and an empty or failed
pull never deletes anything. Every run is recorded in `sync_runs`.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import Member, Message, Subscription

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, joined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, member_id TEXT NOT NULL REFERENCES members(id),
    sender TEXT NOT NULL CHECK (sender IN ('member', 'agent')), agent_name TEXT,
    body TEXT NOT NULL, sent_at TEXT NOT NULL, is_automated INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions (
    member_id TEXT NOT NULL REFERENCES members(id), tier TEXT NOT NULL, status TEXT NOT NULL,
    started_at TEXT NOT NULL, PRIMARY KEY (member_id, started_at)
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL, members INTEGER DEFAULT 0, messages INTEGER DEFAULT 0, subscriptions INTEGER DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_messages_member ON messages(member_id);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def utc_iso(dt: datetime) -> str:
    """Store every timestamp as UTC ISO-8601, so date filters and durations are exact."""
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert(con: sqlite3.Connection, members: Iterable[Member], messages: Iterable[Message],
           subscriptions: Iterable[Subscription], is_automated) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Insert or update everything in one transaction. Nothing is deleted."""
    members, messages, subscriptions = list(members), list(messages), list(subscriptions)
    started = utc_iso(datetime.now(UTC))
    run_id = con.execute("INSERT INTO sync_runs (started_at, status) VALUES (?, 'running')", (started,)).lastrowid
    con.commit()  # record the run on its own, so a failed data transaction can't roll it back
    try:
        with con:
            con.executemany(
                "INSERT INTO members VALUES (:id, :name, :email, :joined_at) ON CONFLICT(id) DO UPDATE SET "
                "name = excluded.name, email = excluded.email",
                [{**m.model_dump(), "joined_at": utc_iso(m.joined_at)} for m in members])
            con.executemany(
                "INSERT INTO messages VALUES (:id, :conversation_id, :member_id, :sender, :agent_name, :body, :sent_at, "
                ":is_automated) ON CONFLICT(id) DO UPDATE SET body = excluded.body, is_automated = excluded.is_automated",
                [{**m.model_dump(), "sent_at": utc_iso(m.sent_at), "is_automated": int(is_automated(m))} for m in messages])
            con.executemany(
                "INSERT INTO subscriptions VALUES (:member_id, :tier, :status, :started_at) "
                "ON CONFLICT(member_id, started_at) DO UPDATE SET tier = excluded.tier, status = excluded.status",
                [{**s.model_dump(), "started_at": utc_iso(s.started_at)} for s in subscriptions])
        counts = {"members": len(members), "messages": len(messages), "subscriptions": len(subscriptions)}
        con.execute("UPDATE sync_runs SET finished_at = ?, status = 'ok', members = ?, messages = ?, subscriptions = ? "
                    "WHERE id = ?", (utc_iso(datetime.now(UTC)), *counts.values(), run_id))
        con.commit()
        return counts
    except Exception as exc:
        con.execute("UPDATE sync_runs SET finished_at = ?, status = 'failed', error = ? WHERE id = ?",
                    (utc_iso(datetime.now(UTC)), str(exc)[:500], run_id))
        con.commit()
        raise
