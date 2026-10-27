from datetime import UTC, date, datetime, timedelta

import pytest

from support_analytics.analytics.business_hours import business_minutes
from support_analytics.analytics.contacts import classify_topic, compute_contacts
from support_analytics.analytics.reports import funnel, kpis, percentile, queue, trend
from support_analytics.core.config import BusinessHours, WorkspaceConfig
from support_analytics.ingest.store import connect

UTC_HOURS = BusinessHours(timezone="UTC")


def t(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)  # Oct 1 2026 is a Thursday


@pytest.mark.parametrize("start,end,expected", [
    (t(4, 10), t(4, 10, 30), 30.0),        # inside one working day
    (t(1, 17, 50), t(4, 9, 10), 20.0),     # Thursday evening to Sunday morning, weekend skipped
    (t(4, 7), t(4, 9, 30), 30.0),          # before opening counts from 09:00
    (t(4, 17), t(5, 10), 120.0),           # overnight
    (t(2, 10), t(3, 15), 0.0),             # Friday to Saturday: no working time
    (t(4, 12), t(4, 11), 0.0),             # end before start
])
def test_business_minutes(start, end, expected) -> None:
    assert business_minutes(start, end, UTC_HOURS) == expected


def test_holidays_and_time_zones() -> None:
    holiday = BusinessHours(timezone="UTC", holidays=[date(2026, 10, 4)])
    assert business_minutes(t(4, 10), t(5, 10), holiday) == 60.0
    dubai = BusinessHours(timezone="Asia/Dubai")
    assert business_minutes(t(4, 4, 30), t(4, 5, 30), dubai) == 30.0  # 08:30-09:30 local


def test_unknown_time_zone_and_weekday_are_rejected() -> None:
    with pytest.raises(ValueError):
        BusinessHours(timezone="Mars/Olympus")
    with pytest.raises(ValueError):
        WorkspaceConfig.model_validate({"business_hours": {"days": {"funday": {"start": "09:00", "end": "17:00"}}}})


@pytest.mark.parametrize("text,topic", [
    ("I can't log in", "access"), ("عايز ألغي الاشتراك", "cancellation"), ("Is there a student discount?", "plans"),
    ("الفيديو مش بيشتغل", "technical"), ("Can I get an invoice?", "billing"), ("مواعيد اللايف؟", "events"),
    ("hello there", "other"),
])
def test_topics(text, topic) -> None:
    assert classify_topic(text, WorkspaceConfig().topics) == topic


def test_percentile_nearest_rank() -> None:
    assert percentile([5, 1, 3], 50) == 3 and percentile([1, 2, 3, 4], 90) == 4 and percentile([], 50) is None


def test_demo_data_reports_are_consistent(demo_db) -> None:
    contacts = compute_contacts(connect(demo_db), WorkspaceConfig(), now=datetime(2026, 10, 23, 18, tzinfo=UTC))
    k = kpis(contacts)
    assert k["contacts"] > 300 and 0 < k["reply_rate"] <= 1
    assert k["replied"] + sum(not c.replied for c in contacts) == k["contacts"]
    assert k["median_first_response_business_min"] <= k["median_first_response_min"]
    q = queue(contacts, 120)
    assert len(q) == k["waiting_on_reply"] and q == sorted(q, key=lambda r: r["waiting_since"])
    steps = funnel(contacts)
    assert [s["count"] for s in steps] == sorted((s["count"] for s in steps), reverse=True)
    assert sum(w["contacts"] for w in trend(contacts)) == k["contacts"]
    assert any(c.contact_id.endswith("#2") for c in contacts)  # returning members create second contacts


def test_custom_plans_and_prices() -> None:
    from support_analytics.ingest.classify import AutomationClassifier
    from support_analytics.ingest.models import Member, Message, Subscription
    from support_analytics.ingest.store import upsert

    con = connect(":memory:")
    when = t(4, 10)
    upsert(con, [Member(id="a", name="A", email="a@x.io", joined_at=when - timedelta(days=90))],
           [Message(id="1", conversation_id="c", member_id="a", sender="member", body="question", sent_at=when),
            Message(id="2", conversation_id="c", member_id="a", sender="agent", agent_name="Ali", body="ok",
                    sent_at=when + timedelta(minutes=5))],
           [Subscription(member_id="a", tier="Starter", status="active", started_at=when - timedelta(days=30)),
            Subscription(member_id="a", tier="Team", status="active", started_at=when + timedelta(days=2))], AutomationClassifier())
    cfg = WorkspaceConfig(tier_order=["Free", "Starter", "Team"], monthly_price={"Free": 0, "Starter": 15, "Team": 45})
    c = compute_contacts(con, cfg, now=t(20, 10))[0]
    assert (c.upgraded_to, c.mrr_gain) == ("Team", 30.0)
