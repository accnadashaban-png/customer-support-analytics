import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from support_analytics.ingest.classify import AutomationClassifier
from support_analytics.ingest.models import Member, Message
from support_analytics.ingest.sources import Batch, CsvSource
from support_analytics.ingest.store import connect, upsert
from support_analytics.ingest.sync import source_from_spec, status, store_batch, sync

classify = AutomationClassifier()
T0 = datetime(2026, 10, 4, 10, tzinfo=UTC)


def member(mid: str) -> Member:
    return Member(id=mid, name=mid, email=f"{mid}@example.com", joined_at=T0 - timedelta(days=30))


def msg(i: str, body: str, sender: str = "member", minutes: int = 0) -> Message:
    return Message(id=i, conversation_id="c", member_id="a", sender=sender, agent_name="Ali" if sender == "agent" else None,
                   body=body, sent_at=T0 + timedelta(minutes=minutes))


def test_classifier() -> None:
    agent = lambda body: msg("x", body, "agent")  # noqa: E731
    assert classify(agent("Your verification\n code is 123456"))
    assert classify(agent("كود التحقق الخاص بك هو 554433"))
    assert not classify(agent("Your code should work now, I reset it"))
    assert not classify(msg("y", "Your verification code is 123456"))  # members are never "automated"


def test_upsert_is_idempotent_and_never_deletes() -> None:
    con = connect(":memory:")
    upsert(con, [member("a")], [msg("1", "hi"), msg("2", "hello", "agent", 5)], [], classify)
    upsert(con, [member("a")], [msg("1", "hi")], [], classify)  # partial re-sync
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    assert [r["status"] for r in status(con)["last_runs"]] == ["ok", "ok"]


def test_empty_batch_changes_nothing() -> None:
    con = connect(":memory:")
    upsert(con, [member("a")], [msg("1", "hi")], [], classify)
    assert store_batch(con, Batch())["status"] == "empty"
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


def test_failed_sync_is_recorded_and_rolled_back() -> None:
    con = connect(":memory:")
    orphan = Message(id="o", conversation_id="c", member_id="ghost", sender="member", body="hi", sent_at=T0)
    with pytest.raises(sqlite3.IntegrityError):
        upsert(con, [], [orphan], [], classify)
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert status(con)["last_runs"][0]["status"] == "failed"


def test_timestamps_are_stored_in_utc_and_naive_ones_rejected() -> None:
    con = connect(":memory:")
    local = Message(id="1", conversation_id="c", member_id="a", sender="member", body="hi",
                    sent_at=datetime(2026, 10, 4, 13, tzinfo=timezone(timedelta(hours=3))))
    upsert(con, [member("a")], [local], [], classify)
    assert con.execute("SELECT sent_at FROM messages").fetchone()[0] == "2026-10-04T10:00:00Z"
    with pytest.raises(ValidationError):
        Message(id="2", conversation_id="c", member_id="a", sender="member", body="hi", sent_at=datetime(2026, 10, 4))


def write(folder, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def test_csv_source_imports_valid_files(tmp_path) -> None:
    write(tmp_path, "members.csv", "id,name,email,joined_at\na,Ana,ana@x.io,2026-01-01T00:00:00Z\n")
    write(tmp_path, "messages.csv", "id,conversation_id,member_id,sender,agent_name,body,sent_at\n"
                                    "1,c,a,member,,I can't log in,2026-10-04T10:00:00+03:00\n"
                                    "2,c,a,agent,Ali,Fixed,2026-10-04T07:20:00Z\n")
    con = connect(":memory:")
    assert sync(con, CsvSource(tmp_path)) == {"status": "ok", "members": 1, "messages": 2, "subscriptions": 0}


def test_csv_source_reports_the_bad_line(tmp_path) -> None:
    write(tmp_path, "members.csv", "id,name,email,joined_at\na,Ana,not-an-email,2026-01-01T00:00:00Z\n")
    write(tmp_path, "messages.csv", "id,conversation_id,member_id,sender,agent_name,body,sent_at\n")
    with pytest.raises(ValueError, match="members.csv line 2"):
        CsvSource(tmp_path).fetch()


def test_source_specs(tmp_path) -> None:
    assert type(source_from_spec("synthetic")).__name__ == "SyntheticSource"
    assert type(source_from_spec(f"csv:{tmp_path}")).__name__ == "CsvSource"
    with pytest.raises(ValueError):
        source_from_spec("ftp:somewhere")
