"""Running a sync: once from the CLI, on a schedule inside the API, or from a pushed batch."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from support_analytics.ingest.classify import AutomationClassifier
from support_analytics.ingest.sources import Batch, CsvSource, JsonSource, Source, SyntheticSource
from support_analytics.ingest.store import upsert, utc_iso

logger = logging.getLogger("support_analytics.sync")


def source_from_spec(spec: str) -> Source:
    """'synthetic', 'csv:<folder>' or 'json:<file>'."""
    kind, _, target = spec.partition(":")
    if kind == "synthetic":
        return SyntheticSource()
    if kind == "csv" and target:
        return CsvSource(Path(target))
    if kind == "json" and target:
        return JsonSource(Path(target))
    raise ValueError(f"unknown source {spec!r}; use synthetic, csv:<folder> or json:<file>")


def store_batch(con: sqlite3.Connection, batch: Batch, classifier: AutomationClassifier | None = None) -> dict[str, Any]:
    """Upsert a batch. An empty batch is recorded and changes nothing."""
    if batch.is_empty():
        now = utc_iso(datetime.now(UTC))
        con.execute("INSERT INTO sync_runs (started_at, finished_at, status) VALUES (?, ?, 'empty')", (now, now))
        con.commit()
        return {"status": "empty"}
    counts = upsert(con, batch.members, batch.messages, batch.subscriptions, classifier or AutomationClassifier())
    return {"status": "ok", **counts}


def sync(con: sqlite3.Connection, source: Source, classifier: AutomationClassifier | None = None) -> dict[str, Any]:
    return store_batch(con, source.fetch(), classifier)


def status(con: sqlite3.Connection, limit: int = 10) -> dict[str, Any]:
    runs = [dict(r) for r in con.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,))]
    watermark = con.execute("SELECT MAX(sent_at) FROM messages").fetchone()[0]
    return {"last_runs": runs, "watermark": watermark}


async def run_periodically(con: sqlite3.Connection, spec: str, interval_s: int, lock: Any) -> None:
    """Background task: sync every `interval_s` seconds. A failed run is logged and retried next time."""
    source = source_from_spec(spec)
    while True:
        try:
            with lock:
                result = await asyncio.to_thread(sync, con, source)
            logger.info("scheduled sync: %s", result)
        except Exception:  # noqa: BLE001 - keep the scheduler alive; the run is recorded as failed
            logger.exception("scheduled sync failed")
        await asyncio.sleep(interval_s)
