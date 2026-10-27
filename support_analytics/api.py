"""FastAPI service for the dashboard.

    python -m support_analytics sync     # load demo data (safe to run again)
    uvicorn support_analytics.api:app
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import metrics
from .classify import AutomationClassifier
from .db import connect, upsert
from .sources import Source, SyntheticSource

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path(os.environ.get("SA_DB_PATH", ROOT / "data" / "support.db"))


def sync(con: sqlite3.Connection, source: Source, classifier: AutomationClassifier | None = None) -> dict[str, Any]:
    """Pull from a source and upsert. An empty pull is recorded and changes nothing."""
    batch = source.fetch()
    if batch.is_empty():
        con.execute("INSERT INTO sync_runs (started_at, finished_at, status) VALUES (?, ?, 'empty')",
                    (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()))
        con.commit()
        return {"status": "empty"}
    counts = upsert(con, batch.members, batch.messages, batch.subscriptions, classifier or AutomationClassifier())
    return {"status": "ok", **counts}


def create_app(db_path: Path = DEFAULT_DB, window_days: int = 14) -> FastAPI:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    lock = threading.Lock()
    app = FastAPI(title="Customer Support Analytics", version="1.0.0")

    def stats() -> list[metrics.ConversationStats]:
        with lock:
            return metrics.conversation_stats(con, window_days)

    def date_range(days: int | None, start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
        try:
            s = datetime.fromisoformat(start).replace(tzinfo=UTC) if start else None
            e = datetime.fromisoformat(end).replace(tzinfo=UTC) + timedelta(days=1) if end else None
        except ValueError as exc:
            raise HTTPException(422, "dates must be YYYY-MM-DD") from exc
        if days and not s:
            latest = con.execute("SELECT MAX(sent_at) FROM messages").fetchone()[0]
            anchor = metrics.parse(latest) if latest else datetime.now(UTC)
            s = anchor - timedelta(days=days)
        return s, e

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/summary")
    def summary(days: int | None = Query(30, ge=1, le=3650), start: str | None = None, end: str | None = None) -> dict[str, Any]:
        s, e = date_range(days, start, end)
        with lock:
            broadcasts = metrics.broadcast_count(con)
        return {"from": s.isoformat() if s else None, "to": e.isoformat() if e else None, "window_days": window_days,
                **metrics.summary(metrics.in_range(stats(), s, e), broadcasts)}

    @app.get("/api/trend")
    def trend(days: int = Query(120, ge=7, le=3650)) -> list[dict[str, Any]]:
        s, _ = date_range(days, None, None)
        return metrics.weekly_trend(metrics.in_range(stats(), s, None))

    @app.get("/api/agents")
    def agents(days: int = Query(30, ge=1, le=3650)) -> list[dict[str, Any]]:
        s, _ = date_range(days, None, None)
        return metrics.by_agent(metrics.in_range(stats(), s, None))

    @app.get("/api/conversations")
    def conversations(view: Literal["all", "last30", "waiting", "upgraded"] = "all",
                      tier: str | None = None, q: str | None = Query(None, max_length=100),
                      start: str | None = None, end: str | None = None,
                      limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        rows = metrics.in_range(stats(), *date_range(30 if view == "last30" else None, start, end))
        if view == "waiting":
            rows = [r for r in rows if r.waiting]
        if view == "upgraded":
            rows = [r for r in rows if r.upgraded_to]
        if tier:
            rows = [r for r in rows if r.current_tier == tier]
        if q:
            needle = q.lower()
            rows = [r for r in rows if needle in r.member_name.lower() or needle in r.email.lower()]
        rows.sort(key=lambda r: r.first_message_at, reverse=True)
        return {"total": len(rows), "rows": metrics.as_dicts(rows[offset:offset + limit])}

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        with lock:
            msgs = [dict(r) for r in con.execute(
                "SELECT sender, agent_name, body, sent_at, is_automated FROM messages WHERE conversation_id = ? "
                "ORDER BY sent_at, id", (conversation_id,))]
        if not msgs:
            raise HTTPException(404, "conversation not found")
        stat = next((s for s in stats() if s.conversation_id == conversation_id), None)
        return {"stats": metrics.as_dicts([stat])[0] if stat else None, "messages": msgs}

    @app.post("/api/sync")
    def run_sync() -> dict[str, Any]:
        with lock:
            return sync(con, SyntheticSource())

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(ROOT / "web" / "index.html")

    return app


app = create_app()
