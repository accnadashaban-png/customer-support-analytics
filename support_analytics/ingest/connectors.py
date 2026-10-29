"""Connect your own support data without reshaping it first.

Two connectors, both driven by one JSON mapping file (see `examples/connect/` and docs/CONNECT.md):

1. MappedFileSource: any chat or helpdesk export (CSV, or JSON with the messages anywhere inside it). The mapping
   says which of your columns is the conversation, the customer, the sender, the text and the time, how your
   export spells "customer" and "agent", and the time zone of timestamps written without one.
2. SqlSource: your own database, read-only. The mapping holds one SELECT per table that returns the expected
   columns; the connection is opened read-only (SQLite `mode=ro`, PostgreSQL read-only transactions), only a
   single SELECT or WITH query is accepted, and rows are capped. Run it on a schedule for a live view.

Both return the same validated Batch as every other source, so every metric rule applies unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from support_analytics.ingest.models import Member, Message, Subscription
from support_analytics.ingest.sources import Batch

MAX_ROWS = 2_000_000
SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|grant|copy|vacuum|truncate)\b",
                       re.IGNORECASE)


class MappingError(ValueError):
    """The mapping or the data does not fit; the message says where."""


# ---------- the mapping file ----------

class Fields(BaseModel):
    """Your column names for each value. Only conversation, customer, sender, text and time are required."""
    conversation_id: str
    member_id: str
    sender: str
    body: str
    sent_at: str
    id: str | None = None             # message id; generated from the other values when missing
    agent_name: str | None = None
    member_name: str | None = None
    email: str | None = None
    automated: str | None = None      # a column that is true for bot or auto-replies, if your platform has one


class SubscriptionFields(BaseModel):
    member_id: str
    tier: str
    status: str
    started_at: str


class Mapping(BaseModel):
    format: str = Field("csv", pattern="^(csv|json)$")
    records: str = Field("", description="JSON only: dotted path to the list of messages, e.g. data.messages")
    fields: Fields
    sender_values: dict[str, list[str]] = Field(
        default_factory=lambda: {"member": ["member", "customer", "user", "end-user", "client", "contact"],
                                 "agent": ["agent", "staff", "admin", "support", "operator", "team"]})
    timezone: str = "UTC"             # for timestamps written without an offset
    time_format: str | None = None    # strptime format when timestamps are not ISO-8601 or epoch numbers
    subscriptions_file: str | None = None
    subscription_fields: SubscriptionFields | None = None
    status_values: dict[str, list[str]] = Field(default_factory=dict)  # e.g. {"active": ["paid", "live"]}


def load_mapping(path: Path) -> Mapping:
    try:
        return Mapping.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise MappingError(f"mapping {path}: {exc}") from exc


# ---------- value conversion ----------

def to_time(value: Any, tz: str, fmt: str | None = None) -> datetime:
    """ISO-8601 (with or without an offset), epoch seconds or milliseconds, or a strptime format."""
    if value is None or str(value).strip() == "":
        raise MappingError("empty timestamp")
    text = str(value).strip()
    if re.fullmatch(r"\d{9,13}(\.\d+)?", text):
        seconds = float(text) / (1000 if len(text.split(".")[0]) == 13 else 1)
        return datetime.fromtimestamp(seconds, UTC)
    try:
        dt = datetime.strptime(text, fmt) if fmt else datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MappingError(f"cannot read the time {text!r}; set time_format in the mapping") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(tz))


def pick(row: dict[str, Any], column: str | None) -> Any:
    """A column by name; a dotted name reads inside nested JSON ("author.role")."""
    if not column:
        return None
    value: Any = row
    for part in column.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def classify(value: Any, choices: dict[str, list[str]], what: str) -> str:
    text = str(value or "").strip().lower()
    for target, spellings in choices.items():
        if text == target or text in (s.lower() for s in spellings):
            return target
    raise MappingError(f"unknown {what} {value!r}; add it to the mapping")


def truthy(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip().lower() in ("1", "true", "yes", "y", "bot", "auto", "automated")


def rows_to_batch(rows: list[dict[str, Any]], m: Mapping, subs: list[dict[str, Any]] | None = None) -> Batch:
    """Validated members, messages and subscriptions from your rows. Errors name the row."""
    f = m.fields
    batch = Batch()
    members: dict[str, Member] = {}
    for n, row in enumerate(rows, start=1):
        try:
            member_id = str(pick(row, f.member_id) or "").strip()
            conversation = str(pick(row, f.conversation_id) or "").strip()
            sent_at = to_time(pick(row, f.sent_at), m.timezone, m.time_format)
            sender = classify(pick(row, f.sender), m.sender_values, "sender")
            body = str(pick(row, f.body) or "")
            message_id = str(pick(row, f.id) or "") or hashlib.sha1(
                f"{conversation}|{member_id}|{sent_at.isoformat()}|{sender}|{body}".encode()).hexdigest()[:16]
            batch.messages.append(Message(
                id=message_id, conversation_id=conversation, member_id=member_id, sender=sender,  # type: ignore[arg-type]
                agent_name=(str(pick(row, f.agent_name)) if sender == "agent" and pick(row, f.agent_name) else None),
                body=body[:20_000], sent_at=sent_at, automated=truthy(pick(row, f.automated))))
            if member_id not in members or (members[member_id].joined_at > sent_at):
                name = str(pick(row, f.member_name) or (members[member_id].name if member_id in members else member_id))
                email = str(pick(row, f.email) or (members[member_id].email if member_id in members else "")).strip()
                members[member_id] = Member(id=member_id, name=name[:200], email=email, joined_at=sent_at)
        except (MappingError, ValidationError) as exc:
            raise MappingError(f"row {n}: {exc}") from exc
    batch.members = list(members.values())
    if subs and m.subscription_fields:
        sf = m.subscription_fields
        statuses = {"active": [], "trial": [], "canceled": [], "past_due": [], "expired": [], **m.status_values}
        for n, row in enumerate(subs, start=1):
            try:
                batch.subscriptions.append(Subscription(
                    member_id=str(pick(row, sf.member_id)), tier=str(pick(row, sf.tier)),
                    status=classify(pick(row, sf.status), statuses, "status"),  # type: ignore[arg-type]
                    started_at=to_time(pick(row, sf.started_at), m.timezone, m.time_format)))
            except (MappingError, ValidationError) as exc:
                raise MappingError(f"subscription row {n}: {exc}") from exc
    return batch


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return [{k.strip(): v for k, v in r.items() if k} for r in csv.DictReader(fh)]


# ---------- 1. any export file ----------

class MappedFileSource:
    def __init__(self, data: Path, mapping: Path | Mapping):
        self.data = Path(data)
        self.mapping = mapping if isinstance(mapping, Mapping) else load_mapping(mapping)
        self.base = self.data.parent

    def fetch(self) -> Batch:
        m = self.mapping
        if m.format == "csv":
            rows = _read_csv(self.data)
        else:
            doc: Any = json.loads(self.data.read_text(encoding="utf-8"))
            for part in [p for p in m.records.split(".") if p]:
                doc = doc.get(part) if isinstance(doc, dict) else None
            if not isinstance(doc, list):
                raise MappingError(f"no list of messages at {m.records!r} in {self.data.name}")
            rows = doc
        subs = _read_csv(self.base / m.subscriptions_file) if m.subscriptions_file else None
        return rows_to_batch(rows, m, subs)


# ---------- 2. your database, read-only ----------

class SqlConfig(BaseModel):
    url: str = Field(description="sqlite:///path/to/file.db or postgresql://readonly_user:...@host/db")
    messages: str = Field(description="SELECT returning: conversation_id, member_id, sender, body, sent_at "
                                      "[, id, agent_name, member_name, email, automated]")
    subscriptions: str | None = Field(None, description="SELECT returning: member_id, tier, status, started_at")
    sender_values: dict[str, list[str]] | None = None
    status_values: dict[str, list[str]] = Field(default_factory=dict)
    timezone: str = "UTC"
    time_format: str | None = None


def check_query(sql: str) -> str:
    body = sql.strip().rstrip(";").strip()
    if not SELECT_ONLY.match(body) or ";" in body or FORBIDDEN.search(body):
        raise MappingError("only a single read-only SELECT (or WITH ... SELECT) query is allowed")
    return body


class SqlSource:
    def __init__(self, config: SqlConfig | Path):
        if isinstance(config, Path):
            try:
                config = SqlConfig.model_validate(json.loads(config.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                raise MappingError(f"connection file: {exc}") from exc
        self.config = config

    def _query(self, sql: str) -> list[dict[str, Any]]:
        sql = check_query(sql)
        url = self.config.url
        if url.startswith("sqlite:///"):
            path = Path(url.removeprefix("sqlite:///"))
            if not path.exists():
                raise MappingError(f"database not found: {path}")
            con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)  # the file cannot be changed
            con.row_factory = sqlite3.Row
            try:
                return [dict(r) for r in con.execute(sql).fetchmany(MAX_ROWS)]
            finally:
                con.close()
        if url.startswith(("postgresql://", "postgres://")):
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # optional dependency
                raise MappingError('PostgreSQL needs: pip install "customer-support-analytics[postgres]"') from exc
            with psycopg.connect(url, row_factory=dict_row, options="-c default_transaction_read_only=on") as pg:
                pg.read_only = True
                return list(pg.execute(sql).fetchmany(MAX_ROWS))  # type: ignore[arg-type]
        raise MappingError("url must start with sqlite:/// or postgresql://")

    def fetch(self) -> Batch:
        c = self.config
        m = Mapping(fields=Fields(conversation_id="conversation_id", member_id="member_id", sender="sender",
                                  body="body", sent_at="sent_at", id="id", agent_name="agent_name",
                                  member_name="member_name", email="email", automated="automated"),
                    timezone=c.timezone, time_format=c.time_format, status_values=c.status_values,
                    subscription_fields=SubscriptionFields(member_id="member_id", tier="tier", status="status",
                                                           started_at="started_at") if c.subscriptions else None)
        if c.sender_values:
            m.sender_values = c.sender_values
        subs = self._query(c.subscriptions) if c.subscriptions else None
        return rows_to_batch(self._query(c.messages), m, subs)
