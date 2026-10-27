import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from support_analytics.api.app import create_app
from support_analytics.core.settings import Settings

NOW = datetime(2026, 10, 23, 18, tzinfo=UTC)
KEY = "test-ingest-key"


@pytest.fixture(scope="module")
def client(demo_db, tmp_path_factory):
    db = tmp_path_factory.mktemp("api") / "support.db"
    db.write_bytes(demo_db.read_bytes())
    settings = Settings(db_path=db, api_keys=[SecretStr(KEY)], sync_source="synthetic", _env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(settings, clock=lambda: NOW))


def test_kpis_and_config(client) -> None:
    k = client.get("/api/kpis?days=30").json()
    assert k["contacts"] > 50 and 0 < k["reply_rate"] <= 1 and 0 <= k["sla_met_rate"] <= 1
    assert k["median_first_response_business_min"] <= k["p90_first_response_business_min"]
    cfg = client.get("/api/config").json()
    assert cfg["sla_first_response_minutes"] == 60 and "other" in cfg["topics"]


def test_queue_matches_waiting_view(client) -> None:
    q = client.get("/api/queue").json()
    waiting = client.get("/api/contacts?view=waiting&limit=500").json()
    assert len(q) == waiting["total"] and all(r["waiting"] for r in waiting["rows"])
    assert [r["waiting_since"] for r in q] == sorted(r["waiting_since"] for r in q)


def test_views_filters_and_breakdowns(client) -> None:
    breached = client.get("/api/contacts?view=breached&limit=500").json()["rows"]
    assert breached and all(r["sla_breached"] for r in breached)
    upgraded = client.get("/api/contacts?view=upgraded&limit=500").json()["rows"]
    assert all(r["upgraded_to"] and r["days_to_upgrade"] <= 14 for r in upgraded)
    topics = client.get("/api/breakdown/topics").json()
    assert sum(t["contacts"] for t in topics) == client.get("/api/kpis?days=30").json()["contacts"]
    assert client.get("/api/breakdown/nope").status_code == 422
    assert client.get("/api/funnel").json()[0]["step"] == "contacted"
    first = client.get("/api/contacts?limit=1").json()["rows"][0]
    found = client.get("/api/contacts", params={"q": first["email"]}).json()["rows"]
    assert any(r["contact_id"] == first["contact_id"] for r in found)


def test_contact_detail_marks_automated_messages(client) -> None:
    rows = client.get("/api/contacts?limit=500").json()["rows"]
    details = [client.get(f"/api/contacts/{r['contact_id'].replace('#', '%23')}").json() for r in rows[:80]]
    assert any(m["is_automated"] for d in details for m in d["messages"])
    assert client.get("/api/contacts/nope%231").status_code == 404


def test_csv_export_is_safe_for_spreadsheets(client) -> None:
    payload = {"members": [{"id": "x1", "name": "=HYPERLINK(\"http://evil\")", "email": "x1@example.com",
                            "joined_at": "2026-01-01T00:00:00Z"}],
               "messages": [{"id": "x1m", "conversation_id": "x1c", "member_id": "x1", "sender": "member",
                             "body": "@SUM(1+1) hello", "sent_at": "2026-10-22T10:00:00Z"}]}
    assert client.post("/api/ingest", json=payload, headers={"X-API-Key": KEY}).json()["status"] == "ok"
    text = client.get("/api/contacts.csv?view=all").text
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text and "'@SUM" in text


def test_ingest_requires_a_valid_key_and_valid_data(client) -> None:
    body = {"members": [], "messages": []}
    assert client.post("/api/ingest", json=body).status_code == 401
    assert client.post("/api/ingest", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    bad = {"messages": [{"id": "1", "conversation_id": "c", "member_id": "m", "sender": "robot", "body": "x",
                         "sent_at": "2026-10-04T10:00:00Z"}]}
    assert client.post("/api/ingest", json=bad, headers={"X-API-Key": KEY}).status_code == 422
    orphan = {"messages": [{"id": "o1", "conversation_id": "c", "member_id": "ghost", "sender": "member", "body": "x",
                            "sent_at": "2026-10-04T10:00:00Z"}]}
    assert client.post("/api/ingest", json=orphan, headers={"X-API-Key": KEY}).status_code == 422
    huge = json.dumps({"members": [], "pad": "x" * 6_000_000})
    assert client.post("/api/ingest", content=huge, headers={"X-API-Key": KEY, "Content-Type": "application/json"}).status_code == 413


def test_ingest_disabled_without_keys(demo_db, tmp_path) -> None:
    db = tmp_path / "s.db"
    db.write_bytes(demo_db.read_bytes())
    c = TestClient(create_app(Settings(db_path=db, _env_file=None), clock=lambda: NOW))  # type: ignore[call-arg]
    assert c.post("/api/ingest", json={}).status_code == 403
    assert c.post("/api/sync").status_code == 403


def test_resync_keeps_numbers_stable(client) -> None:
    before = client.get("/api/kpis?days=30").json()
    assert client.post("/api/sync", headers={"X-API-Key": KEY}).json()["status"] == "ok"
    assert client.get("/api/kpis?days=30").json() == before
    assert client.get("/api/sync/status").json()["last_runs"][0]["status"] == "ok"


def test_validation_and_security_headers(client) -> None:
    assert client.get("/api/contacts?start=not-a-date").status_code == 422
    assert client.get("/api/contacts?view=everything").status_code == 422
    r = client.get("/")
    assert "Support Analytics" in r.text and r.headers["X-Frame-Options"] == "DENY"
