"""FastAPI service and dashboard.

    python -m support_analytics sync          # load data (demo, or --csv / --json your own)
    uvicorn support_analytics.api.app:app
"""
from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator

from support_analytics.analytics import reports
from support_analytics.analytics.contacts import Contact, as_dicts, broadcast_threads, compute_contacts, parse
from support_analytics.core.config import WorkspaceConfig, load_config
from support_analytics.core.settings import ROOT, Settings, get_settings
from support_analytics.ingest.models import Member, Message, Subscription
from support_analytics.ingest.sources import Batch
from support_analytics.ingest.store import connect
from support_analytics.ingest.sync import run_periodically, source_from_spec, status, store_batch, sync

WEB = ROOT / "web" / "index.html"
View = Literal["all", "last30", "waiting", "upgraded", "breached"]
MAX_WEBHOOK_EVENTS = 500


class WebhookMember(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field("", max_length=200)
    email: str = Field("", max_length=320)
    joined_at: AwareDatetime | None = None


class WebhookMessage(BaseModel):
    """One chat or DM message, as a website chat, a DM bridge or an automation tool sends it."""
    message_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(min_length=1, max_length=128)
    sender: Literal["member", "agent"]
    agent_name: str | None = Field(None, max_length=120)
    body: str = Field(max_length=20_000)
    sent_at: AwareDatetime
    automated: bool | None = None
    member: WebhookMember

    @model_validator(mode="after")
    def agent_named(self) -> WebhookMessage:
        if self.sender == "agent" and not self.agent_name and not self.automated:
            raise ValueError("agent messages need agent_name, or automated: true")
        return self


def _csv_safe(value: Any) -> Any:
    """Stop spreadsheet formula injection in exported cells (=, +, -, @ at the start)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def create_app(settings: Settings | None = None, config: WorkspaceConfig | None = None,
               clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> FastAPI:
    settings = settings or get_settings()
    cfg = config or load_config(settings.config_path)
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(settings.db_path)
    lock = threading.Lock()
    cache: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        task = None
        if settings.sync_source and settings.sync_interval_s:
            task = asyncio.create_task(run_periodically(con, settings.sync_source, settings.sync_interval_s, lock))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Customer Support Analytics", version="2.0.0", lifespan=lifespan)
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["GET"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def contacts() -> list[Contact]:
        """Recomputed when data changes or the minute ticks (waiting times depend on now)."""
        with lock:
            version = con.execute("SELECT COALESCE(MAX(id), 0) FROM sync_runs").fetchone()[0]
            key = f"{version}:{clock().strftime('%Y%m%d%H%M')}"
            if cache.get("key") != key:
                cache.update(key=key, contacts=compute_contacts(con, cfg, now=clock()))
            return list(cache["contacts"])

    def period(days: int | None, start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
        try:
            s = datetime.fromisoformat(start).replace(tzinfo=UTC) if start else None
            e = datetime.fromisoformat(end).replace(tzinfo=UTC) + timedelta(days=1) if end else None
        except ValueError as exc:
            raise HTTPException(422, "dates must be YYYY-MM-DD") from exc
        if days and not s:
            with lock:
                latest = con.execute("SELECT MAX(sent_at) FROM messages").fetchone()[0]
            s = (parse(latest) if latest else clock()) - timedelta(days=days)
        return s, e

    def filtered(view: str, tier: str | None, topic: str | None, agent: str | None, q: str | None,
                 start: str | None, end: str | None) -> list[Contact]:
        rows = reports.in_range(contacts(), *period(30 if view == "last30" else None, start, end))
        rows = [c for c in rows if (view != "waiting" or c.waiting) and (view != "upgraded" or c.upgraded_to)
                and (view != "breached" or c.sla_breached) and (not tier or c.current_tier == tier)
                and (not topic or c.topic == topic) and (not agent or c.agent == agent)]
        if q:
            needle = q.lower()
            rows = [c for c in rows if needle in c.member_name.lower() or needle in c.email.lower()]
        return sorted(rows, key=lambda c: c.first_message_at, reverse=True)

    def require_key(request: Request) -> None:
        if not settings.api_keys:
            raise HTTPException(403, "ingestion is disabled: set SA_API_KEYS")
        given = request.headers.get("X-API-Key", "")
        if not any(hmac.compare_digest(given.encode(), k.get_secret_value().encode()) for k in settings.api_keys):
            raise HTTPException(401, "invalid API key")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    def config_view() -> dict[str, Any]:
        bh = cfg.business_hours
        return {"timezone": bh.timezone, "business_days": {d: f"{h.start}-{h.end}" for d, h in bh.days.items()},
                "holidays": [str(h) for h in bh.holidays], "sla_first_response_minutes": cfg.sla_first_response_minutes,
                "contact_gap_hours": cfg.contact_gap_hours, "upgrade_window_days": cfg.upgrade_window_days,
                "alert_after_minutes": cfg.alert_after_minutes, "topics": sorted(cfg.topics) + ["other"],
                "tiers": cfg.tier_order, "currency": cfg.currency}

    @app.get("/api/kpis")
    def kpis(days: int | None = Query(30, ge=1, le=3650), start: str | None = None, end: str | None = None,
             tier: str | None = None, topic: str | None = None) -> dict[str, Any]:
        s, e = period(days, start, end)
        rows = [c for c in reports.in_range(contacts(), s, e) if (not tier or c.tier_at_contact == tier)
                and (not topic or c.topic == topic)]
        with lock:
            broadcasts = broadcast_threads(con)
        return {"from": s.isoformat() if s else None, "to": e.isoformat() if e else None,
                **reports.kpis(rows), "broadcast_only_excluded": broadcasts, "currency": cfg.currency}

    @app.get("/api/queue")
    def open_queue() -> list[dict[str, Any]]:
        return reports.queue(contacts(), cfg.alert_after_minutes)

    @app.get("/api/trend")
    def trend(days: int = Query(120, ge=7, le=3650)) -> list[dict[str, Any]]:
        return reports.trend(reports.in_range(contacts(), period(days, None, None)[0], None))

    @app.get("/api/breakdown/{dimension}")
    def breakdown(dimension: Literal["agents", "topics", "tiers"], days: int = Query(30, ge=1, le=3650)) -> list[dict[str, Any]]:
        rows = reports.in_range(contacts(), period(days, None, None)[0], None)
        return {"agents": reports.by_agent, "topics": reports.by_topic, "tiers": reports.by_tier}[dimension](rows)

    @app.get("/api/funnel")
    def funnel(days: int = Query(30, ge=1, le=3650)) -> list[dict[str, Any]]:
        return reports.funnel(reports.in_range(contacts(), period(days, None, None)[0], None))

    @app.get("/api/contacts")
    def list_contacts(view: View = "all", tier: str | None = None, topic: str | None = None, agent: str | None = None,
                      q: str | None = Query(None, max_length=100), start: str | None = None, end: str | None = None,
                      limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
        rows = filtered(view, tier, topic, agent, q, start, end)
        return {"total": len(rows), "rows": as_dicts(rows[offset:offset + limit])}

    @app.get("/api/contacts.csv")
    def export_csv(view: View = "all", tier: str | None = None, topic: str | None = None, agent: str | None = None,
                   q: str | None = Query(None, max_length=100), start: str | None = None, end: str | None = None) -> Response:
        rows = as_dicts(filtered(view, tier, topic, agent, q, start, end))
        buffer = io.StringIO()
        if rows:
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows({k: _csv_safe(v) for k, v in r.items()} for r in rows)
        return Response("﻿" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="contacts-{view}.csv"'})

    @app.get("/api/contacts/{contact_id}")
    def contact_detail(contact_id: str) -> dict[str, Any]:
        contact = next((c for c in contacts() if c.contact_id == contact_id), None)
        if contact is None:
            raise HTTPException(404, "contact not found")
        with lock:
            msgs = [dict(r) for r in con.execute(
                "SELECT sender, agent_name, body, sent_at, is_automated FROM messages WHERE conversation_id = ? "
                "AND sent_at >= ? AND sent_at <= ? ORDER BY sent_at, id",
                (contact.conversation_id, contact.first_message_at, contact.last_message_at))]
        return {"contact": as_dicts([contact])[0], "messages": msgs}

    @app.get("/api/sync/status")
    def sync_status() -> dict[str, Any]:
        with lock:
            return {**status(con), "scheduled": bool(settings.sync_source and settings.sync_interval_s),
                    "source": settings.sync_source.split(":", 1)[0] if settings.sync_source else None}

    @app.post("/api/sync")
    def run_sync(request: Request) -> dict[str, Any]:
        require_key(request)
        if not settings.sync_source:
            raise HTTPException(400, "no SA_SYNC_SOURCE configured")
        with lock:
            return sync(con, source_from_spec(settings.sync_source))

    async def read_body(request: Request) -> bytes:
        require_key(request)
        declared = int(request.headers.get("content-length") or 0)
        if declared > settings.max_ingest_bytes:
            raise HTTPException(413, "payload too large")
        body = await request.body()
        if len(body) > settings.max_ingest_bytes:
            raise HTTPException(413, "payload too large")
        return body

    def invalid(exc: Exception) -> HTTPException:
        # never echo the submitted values back: they can hold personal data
        detail = (exc.errors(include_url=False, include_context=False, include_input=False)
                  if isinstance(exc, ValidationError) else "invalid JSON body")
        return HTTPException(422, detail)

    @app.post("/api/ingest")
    async def ingest(request: Request) -> dict[str, Any]:
        """Push members, messages and subscriptions from any system. Re-sending the same data changes nothing."""
        body = await read_body(request)
        try:
            data = json.loads(body)
            batch = Batch([Member.model_validate(m) for m in data.get("members", [])],
                          [Message.model_validate(m) for m in data.get("messages", [])],
                          [Subscription.model_validate(s) for s in data.get("subscriptions", [])])
        except (ValueError, AttributeError) as exc:
            raise invalid(exc) from exc
        with lock:
            try:
                return store_batch(con, batch)
            except sqlite3.IntegrityError as exc:
                raise HTTPException(422, "every message and subscription must refer to a member in the store or in the batch") from exc

    @app.post("/api/webhook/message")
    async def webhook(request: Request) -> dict[str, Any]:
        """Live feed: one message (or a list) per call, as it happens. Unknown members are created on first sight,
        known ones keep their join date. Delivering the same message twice changes nothing."""
        body = await read_body(request)
        try:
            data = json.loads(body)
            items = data if isinstance(data, list) else [data]
            if len(items) > MAX_WEBHOOK_EVENTS:
                raise HTTPException(413, f"at most {MAX_WEBHOOK_EVENTS} messages per call")
            events = [WebhookMessage.model_validate(item) for item in items]
        except (ValueError, AttributeError) as exc:
            raise invalid(exc) from exc
        with lock:
            members: dict[str, Member] = {}
            for e in sorted(events, key=lambda e: e.sent_at):
                if e.member.id in members:
                    continue
                known = con.execute("SELECT 1 FROM members WHERE id = ?", (e.member.id,)).fetchone()
                try:
                    members[e.member.id] = Member(id=e.member.id, name=e.member.name or ("" if known else e.member.id),
                                                  email=e.member.email, joined_at=e.member.joined_at or e.sent_at)
                except ValidationError as exc:
                    raise invalid(exc) from exc
            messages = [Message(id=e.message_id, conversation_id=e.conversation_id, member_id=e.member.id, sender=e.sender,
                                agent_name=e.agent_name, body=e.body, sent_at=e.sent_at, automated=e.automated) for e in events]
            result = store_batch(con, Batch(list(members.values()), messages, []))
        return {**result, "received": len(events)}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(WEB.parent / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
