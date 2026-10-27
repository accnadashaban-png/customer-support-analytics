"""Hand-built conversations with known answers, so every metric is checked exactly."""
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from support_analytics import metrics
from support_analytics.classify import AutomationClassifier
from support_analytics.db import connect, upsert
from support_analytics.models import Member, Message, Subscription
from support_analytics.sources import Batch

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
classify = AutomationClassifier()


def msg(cid, mid, sender, body, minutes, agent=None, seq=0):
    return Message(id=f"{cid}_{seq}", conversation_id=cid, member_id=mid, sender=sender, agent_name=agent,
                   body=body, sent_at=T0 + timedelta(minutes=minutes))


def member(mid):
    return Member(id=mid, name=f"Member {mid}", email=f"{mid}@example.com", joined_at=T0 - timedelta(days=90))


def sub(mid, tier, status, days):
    return Subscription(member_id=mid, tier=tier, status=status, started_at=T0 + timedelta(days=days))


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "t.db")
    members = [member(m) for m in ("a", "b", "c", "d", "e", "f")]
    messages = [
        # a: an automated code arrives first; the human reply 30 min later is the real first response
        msg("A", "a", "member", "I can't log in", 0), msg("A", "a", "agent", "Your  VERIFICATION code is 482913", 0.5, "Sara", 1),
        msg("A", "a", "agent", "Fixed, try again", 30, "Omar", 2),
        # b: never answered
        msg("B", "b", "member", "Hello?", 10),
        # c: answered, member closes with thanks -> not waiting
        msg("C", "c", "member", "How do I cancel?", 0), msg("C", "c", "agent", "Here's how", 90, "Mona", 1),
        msg("C", "c", "member", "Thanks!", 100, seq=2),
        # d: broadcast only -> excluded
        msg("D", "d", "agent", "Your membership renews on 2026-11-01.", 0, "Sara"),
        # e: answered, then a new question nobody answered -> waiting since the new question
        msg("E", "e", "member", "Invoice please", 0), msg("E", "e", "agent", "Sent", 15, "Omar", 1),
        msg("E", "e", "member", "I didn't get it", 60, seq=2),
        # f: a 3-hour reply
        msg("F", "f", "member", "Pro vs Elite?", 0), msg("F", "f", "agent", "Elite adds...", 180, "Sara", 1),
    ]
    subs = [
        sub("a", "Basic", "active", -30), sub("a", "Pro", "active", 5),      # upgrade inside 14 days
        sub("b", "Basic", "active", -30), sub("b", "Pro", "active", 20),     # outside the window
        sub("c", "Pro", "active", -30), sub("c", "Pro", "canceled", 3),      # cancellation is not an upgrade
        sub("e", "Free", "active", -30), sub("e", "Basic", "trial", 2),      # trial counts as paid access
        sub("f", "Elite", "active", -30), sub("f", "Pro", "active", 4),      # downgrade is not an upgrade
    ]
    upsert(c, members, messages, subs, classify)
    return c


def by_id(con):
    return {s.conversation_id: s for s in metrics.conversation_stats(con)}


def test_bots_never_count_as_a_reply(con):
    a = by_id(con)["A"]
    assert a.first_response_min == 30.0 and a.agent == "Omar" and a.replied


def test_broadcast_only_threads_are_excluded(con):
    assert "D" not in by_id(con) and metrics.broadcast_count(con) == 1


def test_waiting_on_reply(con):
    s = by_id(con)
    assert s["B"].waiting and not s["B"].replied
    assert not s["C"].waiting  # a closing "Thanks!" needs no answer
    assert s["E"].waiting and s["E"].waiting_since == "2026-10-01T11:00:00Z"


def test_upgrade_rules(con):
    s = by_id(con)
    assert s["A"].upgraded_to == "Pro" and s["A"].days_to_upgrade == 5.0
    assert s["B"].upgraded_to is None             # 20 days later, outside the 14-day window
    assert s["C"].upgraded_to is None and s["C"].current_tier == "Free"
    assert s["E"].upgraded_to == "Basic"          # trial is paid access
    assert s["F"].upgraded_to is None             # downgrade


def test_summary_numbers(con):
    s = metrics.summary(list(by_id(con).values()), broadcasts=1)
    assert s["conversations"] == 5
    assert s["reply_rate"] == 0.8                 # A, C, E, F replied; B didn't
    assert s["median_first_response_min"] == 30.0  # [15, 30, 90, 180] -> nearest-rank p50 = 30
    assert s["p90_first_response_min"] == 180.0
    assert s["waiting_on_reply"] == 2 and s["upgrades"] == 2


def test_percentile_nearest_rank():
    assert metrics.percentile([5, 1, 3], 50) == 3 and metrics.percentile([1, 2, 3, 4], 90) == 4
    assert metrics.percentile([], 50) is None


def test_by_agent_and_trend(con):
    agents = {r["agent"]: r for r in metrics.by_agent(list(by_id(con).values()))}
    assert agents["Omar"]["first_replies"] == 2 and "Sara" in agents
    assert metrics.weekly_trend(list(by_id(con).values()))[0]["conversations"] == 5


def test_local_times_are_stored_as_utc(tmp_path):
    c = connect(tmp_path / "tz.db")
    cairo = timezone(timedelta(hours=3))
    m = Message(id="x", conversation_id="X", member_id="z", sender="member", body="hi",
                sent_at=datetime(2026, 10, 1, 13, 0, tzinfo=cairo))
    upsert(c, [member("z")], [m], [], classify)
    assert c.execute("SELECT sent_at FROM messages").fetchone()[0] == "2026-10-01T10:00:00Z"


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValidationError):
        Message(id="x", conversation_id="X", member_id="z", sender="member", body="hi", sent_at=datetime(2026, 10, 1))


def test_classifier():
    agent = lambda body: Message(id="1", conversation_id="c", member_id="m", sender="agent", body=body, sent_at=T0)  # noqa: E731
    assert classify(agent("Your verification\n code is 123456"))
    assert classify(agent("كود التحقق الخاص بك هو 554433"))
    assert not classify(agent("Your code should work now, I reset it"))
    member_msg = Message(id="2", conversation_id="c", member_id="m", sender="member", body="Your verification code is 123456", sent_at=T0)
    assert not classify(member_msg)  # members are never "automated"


def test_sync_is_idempotent_and_never_deletes(con):
    before = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    upsert(con, [member("a")], [msg("A", "a", "member", "I can't log in", 0)], [], classify)  # partial re-sync
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before
    assert con.execute("SELECT COUNT(*) FROM sync_runs WHERE status = 'ok'").fetchone()[0] == 2


def test_empty_pull_changes_nothing(con):
    from support_analytics.api import sync

    class Empty:
        def fetch(self):
            return Batch()

    before = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert sync(con, Empty())["status"] == "empty"
    assert con.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == before


def test_failed_sync_is_recorded_and_rolled_back(con):
    bad = Message(id="new", conversation_id="N", member_id="ghost", sender="member", body="hi", sent_at=T0)
    with pytest.raises(sqlite3.IntegrityError):
        upsert(con, [], [bad], [], classify)  # unknown member violates the foreign key
    assert con.execute("SELECT COUNT(*) FROM messages WHERE id = 'new'").fetchone()[0] == 0
    assert con.execute("SELECT status FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "failed"
