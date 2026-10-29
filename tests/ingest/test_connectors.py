"""Connect real exports and databases: column mapping, time zones, nested JSON, read-only SQL."""
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from support_analytics.analytics.contacts import compute_contacts
from support_analytics.core.config import WorkspaceConfig
from support_analytics.ingest.connectors import (
    MappedFileSource,
    MappingError,
    SqlConfig,
    SqlSource,
    check_query,
    to_time,
)
from support_analytics.ingest.store import connect
from support_analytics.ingest.sync import source_from_spec, sync

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "connect"
UTC_CFG = WorkspaceConfig.model_validate({"business_hours": {"timezone": "UTC"}})


def test_helpdesk_export_with_its_own_columns(tmp_path) -> None:
    con = connect(tmp_path / "s.db")
    result = sync(con, MappedFileSource(EXAMPLES / "helpdesk-export.csv", EXAMPLES / "helpdesk-mapping.json"))
    assert result["status"] == "ok" and result["members"] == 3 and result["messages"] == 7
    contacts = {c.contact_id: c for c in compute_contacts(con, UTC_CFG, now=datetime(2026, 10, 22, tzinfo=UTC))}
    first = contacts["T-1001#1"]
    # Cairo 09:15 is 06:15 UTC; the bot's instant receipt is not a reply, Hana's answer 27 minutes later is
    assert first.first_message_at == "2026-10-20T06:15:00Z" and first.first_response_min == 27.0 and first.agent == "Hana"
    assert first.topic == "connection" and not first.waiting  # the closing "thanks" needs no reply
    assert contacts["T-1003#1"].waiting and contacts["T-1003#1"].topic == "billing"
    assert sync(con, MappedFileSource(EXAMPLES / "helpdesk-export.csv", EXAMPLES / "helpdesk-mapping.json"))["messages"] == 7
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 7  # re-importing changes nothing


def test_nested_json_chat_export_with_epoch_times(tmp_path) -> None:
    con = connect(tmp_path / "s.db")
    sync(con, source_from_spec(f"mapped:{EXAMPLES / 'chat-export.json'}|{EXAMPLES / 'chat-mapping.json'}"))
    contacts = {c.contact_id: c for c in compute_contacts(con, UTC_CFG, now=datetime(2026, 10, 23, tzinfo=UTC))}
    assert contacts["wa-501#1"].first_response_min == 30.0 and contacts["wa-501#1"].topic == "device"
    assert contacts["wa-502#1"].waiting


def test_mapping_errors_name_the_row(tmp_path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("Ticket ID,Customer ID,Author Type,Message,Created At\nT1,C1,robot,hi,2026-10-20 09:00\n", encoding="utf-8")
    mapping = json.loads((EXAMPLES / "helpdesk-mapping.json").read_text(encoding="utf-8"))
    with pytest.raises(MappingError, match=r"row 1: unknown sender 'robot'"):
        MappedFileSource(bad, _write(tmp_path, mapping)).fetch()
    with pytest.raises(MappingError, match="time_format"):
        to_time("20/10/2026", "UTC")
    assert to_time("1761040800", "UTC") == to_time("1761040800000", "UTC") == datetime(2025, 10, 21, 10, tzinfo=UTC)


def _write(tmp_path, mapping) -> Path:
    path = tmp_path / "m.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return path


@pytest.fixture
def helpdesk_db(tmp_path) -> Path:
    """A helpdesk database with its own schema, nothing like ours."""
    path = tmp_path / "helpdesk.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE customers (id TEXT PRIMARY KEY, full_name TEXT, email TEXT);
        CREATE TABLE tickets (id TEXT PRIMARY KEY, customer_id TEXT);
        CREATE TABLE replies (id INTEGER PRIMARY KEY, ticket_id TEXT, author_kind TEXT, author_name TEXT, content TEXT,
                              created_at TEXT, is_bot INTEGER);
        CREATE TABLE plan_changes (customer_id TEXT, plan TEXT, state TEXT, changed_at TEXT);
        INSERT INTO customers VALUES ('C1', 'Nour Samir', 'nour@example.com');
        INSERT INTO tickets VALUES ('T1', 'C1');
        INSERT INTO replies VALUES (1, 'T1', 'customer', NULL, 'How much is the Pro plan?', '2026-10-20T10:00:00Z', 0),
                                   (2, 'T1', 'staff', 'Omar', 'It is 29 USD a month.', '2026-10-20T10:12:00Z', 0);
        INSERT INTO plan_changes VALUES ('C1', 'Basic', 'paid', '2026-01-01T00:00:00Z'),
                                        ('C1', 'Pro', 'paid', '2026-10-22T00:00:00Z');
    """)
    con.commit()
    con.close()
    return path


def test_read_only_database_connection(tmp_path, helpdesk_db) -> None:
    cfg = json.loads((EXAMPLES / "database-connection.json").read_text(encoding="utf-8"))
    cfg["url"] = f"sqlite:///{helpdesk_db.as_posix()}"
    con = connect(tmp_path / "s.db")
    assert sync(con, SqlSource(SqlConfig.model_validate(cfg)))["messages"] == 2
    c = compute_contacts(con, UTC_CFG, now=datetime(2026, 10, 23, tzinfo=UTC))[0]
    assert c.first_response_min == 12.0 and c.topic == "plans" and c.upgraded_to == "Pro" and c.mrr_gain == 20.0


@pytest.mark.parametrize("sql", ["DELETE FROM replies", "SELECT 1; DROP TABLE replies", "UPDATE replies SET content = ''",
                                 "ATTACH DATABASE 'x.db' AS x", "PRAGMA writable_schema = 1"])
def test_only_a_single_select_is_accepted(sql) -> None:
    with pytest.raises(MappingError, match="read-only SELECT"):
        check_query(sql)


def test_the_database_file_is_opened_read_only(helpdesk_db, monkeypatch) -> None:
    """Second layer: even a write that got past the query check is refused, because the file is opened read-only."""
    import support_analytics.ingest.connectors as connectors

    monkeypatch.setattr(connectors, "check_query", lambda sql: sql)
    source = SqlSource(SqlConfig(url=f"sqlite:///{helpdesk_db.as_posix()}", messages="SELECT 1"))
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        source._query("DELETE FROM replies")
