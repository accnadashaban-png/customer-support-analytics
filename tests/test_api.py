import pytest
from fastapi.testclient import TestClient

from support_analytics.api import create_app, sync
from support_analytics.db import connect
from support_analytics.sources import SyntheticSource


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    path = tmp_path_factory.mktemp("api") / "support.db"
    sync(connect(path), SyntheticSource(seed=7))
    return TestClient(create_app(path))


def test_summary_is_consistent(client):
    s = client.get("/api/summary?days=30").json()
    assert s["conversations"] > 50 and 0 < s["reply_rate"] <= 1
    assert s["median_first_response_min"] <= s["p90_first_response_min"]
    unanswered = round(s["conversations"] * (1 - s["reply_rate"]))
    assert s["waiting_on_reply"] >= unanswered  # every unanswered thread is waiting


def test_views_and_filters(client):
    waiting = client.get("/api/conversations?view=waiting&limit=500").json()
    assert waiting["total"] > 0 and all(r["waiting"] for r in waiting["rows"])
    upgraded = client.get("/api/conversations?view=upgraded&limit=500").json()
    assert all(r["upgraded_to"] and r["days_to_upgrade"] <= 14 for r in upgraded["rows"])
    pro = client.get("/api/conversations?tier=Pro&limit=500").json()
    assert all(r["current_tier"] == "Pro" for r in pro["rows"])
    first = client.get("/api/conversations?limit=1").json()["rows"][0]
    found = client.get("/api/conversations", params={"q": first["email"]}).json()
    assert any(r["conversation_id"] == first["conversation_id"] for r in found["rows"])


def test_detail_marks_automated_messages(client):
    rows = client.get("/api/conversations?limit=500").json()["rows"]
    details = [client.get(f"/api/conversations/{r['conversation_id']}").json() for r in rows[:80]]
    assert any(m["is_automated"] for d in details for m in d["messages"])
    assert client.get("/api/conversations/nope").status_code == 404


def test_trend_agents_and_validation(client):
    assert len(client.get("/api/trend?days=120").json()) >= 15
    assert {"agent", "first_replies", "median_first_response_min"} <= client.get("/api/agents").json()[0].keys()
    assert client.get("/api/conversations?start=not-a-date").status_code == 422
    assert client.get("/api/conversations?view=everything").status_code == 422
    assert client.get("/api/summary?days=0").status_code == 422


def test_resync_keeps_numbers_stable(client):
    before = client.get("/api/summary?days=30").json()
    assert client.post("/api/sync").json()["status"] == "ok"
    assert client.get("/api/summary?days=30").json() == before


def test_dashboard_is_served(client):
    assert "Support Analytics" in client.get("/").text
