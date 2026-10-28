"""Live webhook: one message per call from a website chat, a DM bridge or an automation tool."""
from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from support_analytics.api.app import create_app
from support_analytics.core.settings import Settings

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)  # Thursday 14:00 in Cairo, inside business hours
KEY = "test-webhook-key"
H = {"X-API-Key": KEY}


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path / "live.db", api_keys=[SecretStr(KEY)], _env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(settings, clock=lambda: NOW))


def event(mid, sender="member", at="2026-10-22T08:00:00Z", body="hi, I can't log in", member="dm-55", **extra):
    e = {"message_id": mid, "conversation_id": "dm-thread-1", "sender": sender, "body": body, "sent_at": at,
         "member": {"id": member, "name": "Salma"}}
    if sender == "agent":
        e["agent_name"] = "Omar"
    return {**e, **extra}


def test_message_then_reply_gives_an_exact_first_response(client) -> None:
    assert client.post("/api/webhook/message", json=event("m1"), headers=H).json()["received"] == 1
    queue = client.get("/api/queue").json()
    assert [r["member_name"] for r in queue] == ["Salma"]          # waiting right away, no email needed
    client.post("/api/webhook/message", json=event("a1", "agent", "2026-10-22T08:25:00Z", "Sorry about that, fixed now"),
                headers=H)
    c = client.get("/api/contacts?view=all").json()["rows"][0]
    assert c["first_response_min"] == 25 and c["first_response_business_min"] == 25 and c["sla_met"] is True
    assert client.get("/api/queue").json() == []


def test_redelivery_is_harmless_and_the_name_is_kept(client) -> None:
    for _ in range(3):  # webhooks are retried by senders; the same message must count once
        client.post("/api/webhook/message", json=event("m1"), headers=H)
    later = event("m2", at="2026-10-22T09:00:00Z", body="still waiting")
    later["member"] = {"id": "dm-55"}  # later events may carry the id only
    client.post("/api/webhook/message", json=later, headers=H)
    contact_id = client.get("/api/contacts").json()["rows"][0]["contact_id"]
    detail = client.get("/api/contacts/" + quote(contact_id, safe="")).json()
    assert len(detail["messages"]) == 2 and detail["contact"]["member_name"] == "Salma"


def test_platform_flag_marks_automatic_replies(client) -> None:
    client.post("/api/webhook/message", json=event("m1"), headers=H)
    auto = event("a0", "agent", "2026-10-22T08:00:05Z", "Thanks for your message! A teammate will reply soon.",
                 automated=True)
    del auto["agent_name"]
    client.post("/api/webhook/message", json=auto, headers=H)
    c = client.get("/api/contacts").json()["rows"][0]
    assert c["replied"] is False and c["waiting"] is True        # an auto-acknowledgement is not a reply


def test_batches_of_events_are_accepted(client) -> None:
    batch = [event("m1"), event("a1", "agent", "2026-10-22T08:10:00Z", "Done")]
    assert client.post("/api/webhook/message", json=batch, headers=H).json()["messages"] == 2


def test_webhook_security_and_validation(client) -> None:
    assert client.post("/api/webhook/message", json=event("m1")).status_code == 401
    assert client.post("/api/webhook/message", json=event("m1"), headers={"X-API-Key": "nope"}).status_code == 401
    no_name = event("a1", "agent")
    del no_name["agent_name"]
    assert client.post("/api/webhook/message", json=no_name, headers=H).status_code == 422
    naive = event("m1", at="2026-10-22T08:00:00")                  # a time without a zone is ambiguous
    assert client.post("/api/webhook/message", json=naive, headers=H).status_code == 422
    secret_text = event("m1", sender="robot", body="my card is 4111 1111 1111 1111")
    r = client.post("/api/webhook/message", json=secret_text, headers=H)
    assert r.status_code == 422 and "4111" not in r.text            # errors never echo what was sent
    assert client.post("/api/webhook/message", json=[event(f"x{i}") for i in range(501)], headers=H).status_code == 413
    assert client.post("/api/webhook/message", content=b"{not json", headers={**H, "Content-Type": "application/json"}).status_code == 422
