"""Support metrics, computed per conversation and then aggregated.

Definitions (kept strict on purpose, because accuracy is the point of the tool):
- Inbound conversation: the member wrote at least one message. Conversations that only
  contain messages we sent (broadcasts, reminders) are excluded from team metrics.
- First response time: from the member's first message to the first *human* agent
  reply after it. Automated messages never count as a reply.
- Waiting on reply: the latest message from a person is the member's, with no human
  reply after it. A closing message on its own ("thanks", "شكرا", "تمام") doesn't need a reply.
- Upgrade after support: the member moved to a higher paid tier within `window_days`
  after their first message. `trial` counts as paid access; ended statuses do not.
"""
from __future__ import annotations

import math
import re
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .models import has_access, tier_rank

CLOSING = re.compile(r"^\s*(thanks?( you)?|thx|ok(ay)?|great|perfect|شكرا|شكرًا|متشكر|تمام|تسلم|مشكور)[\s!.,🙏❤️]*$",
                     re.IGNORECASE)


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (p50 = median of the sorted values, by rank)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


@dataclass
class ConversationStats:
    conversation_id: str
    member_id: str
    member_name: str
    email: str
    first_message_at: str
    last_message_at: str
    messages: int
    first_response_min: float | None
    replied: bool
    waiting: bool
    waiting_since: str | None
    agent: str | None
    tier_at_contact: str
    current_tier: str
    upgraded_to: str | None
    days_to_upgrade: float | None


def _tier_at(subs: list[sqlite3.Row], moment: datetime) -> str:
    """The member's tier at a moment: the latest change at or before it, if it still gives access."""
    current = "Free"
    for s in subs:  # sorted by started_at
        if parse(s["started_at"]) <= moment:
            current = s["tier"] if has_access(s["status"]) else "Free"
    return current


def conversation_stats(con: sqlite3.Connection, window_days: int = 14) -> list[ConversationStats]:
    members = {r["id"]: r for r in con.execute("SELECT id, name, email FROM members")}
    subs: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute("SELECT member_id, tier, status, started_at FROM subscriptions ORDER BY started_at"):
        subs.setdefault(r["member_id"], []).append(r)
    convs: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute("SELECT conversation_id, member_id, sender, agent_name, body, sent_at, is_automated "
                         "FROM messages ORDER BY sent_at, id"):
        convs.setdefault(r["conversation_id"], []).append(r)

    out: list[ConversationStats] = []
    for cid, msgs in convs.items():
        member_msgs = [m for m in msgs if m["sender"] == "member"]
        if not member_msgs:
            continue  # broadcast-only: not a support conversation
        first_at = parse(member_msgs[0]["sent_at"])
        human = [m for m in msgs if m["sender"] == "agent" and not m["is_automated"]]
        first_reply = next((m for m in human if parse(m["sent_at"]) > first_at), None)

        people = [m for m in msgs if m["sender"] == "member" or not m["is_automated"]]
        waiting_since = None
        if people[-1]["sender"] == "member":
            last_human = max((parse(m["sent_at"]) for m in human), default=None)
            unanswered = [m for m in member_msgs if last_human is None or parse(m["sent_at"]) > last_human]
            if not all(CLOSING.match(m["body"]) for m in unanswered):
                waiting_since = unanswered[0]["sent_at"]

        member_subs = subs.get(member_msgs[0]["member_id"], [])
        at_contact = _tier_at(member_subs, first_at)
        upgrade = next((s for s in member_subs
                        if first_at < parse(s["started_at"]) <= first_at + timedelta(days=window_days)
                        and has_access(s["status"]) and tier_rank(s["tier"]) > tier_rank(at_contact)), None)
        member = members[member_msgs[0]["member_id"]]
        out.append(ConversationStats(
            conversation_id=cid, member_id=member["id"], member_name=member["name"], email=member["email"],
            first_message_at=member_msgs[0]["sent_at"], last_message_at=msgs[-1]["sent_at"], messages=len(msgs),
            first_response_min=round((parse(first_reply["sent_at"]) - first_at).total_seconds() / 60, 1)
            if first_reply else None,
            replied=first_reply is not None, waiting=waiting_since is not None, waiting_since=waiting_since,
            agent=first_reply["agent_name"] if first_reply else None, tier_at_contact=at_contact,
            current_tier=_tier_at(member_subs, datetime.max.replace(tzinfo=UTC)),
            upgraded_to=upgrade["tier"] if upgrade else None,
            days_to_upgrade=round((parse(upgrade["started_at"]) - first_at).total_seconds() / 86400, 1) if upgrade else None,
        ))
    return out


def in_range(stats: list[ConversationStats], start: datetime | None, end: datetime | None) -> list[ConversationStats]:
    return [s for s in stats if (start is None or parse(s.first_message_at) >= start)
            and (end is None or parse(s.first_message_at) < end)]


def summary(stats: list[ConversationStats], broadcasts: int = 0) -> dict[str, Any]:
    times = [s.first_response_min for s in stats if s.first_response_min is not None]
    n = len(stats)
    return {
        "conversations": n,
        "reply_rate": round(sum(s.replied for s in stats) / n, 3) if n else None,
        "median_first_response_min": percentile(times, 50),
        "p90_first_response_min": percentile(times, 90),
        "mean_first_response_min": round(statistics.fmean(times), 1) if times else None,
        "waiting_on_reply": sum(s.waiting for s in stats),
        "upgrades": sum(s.upgraded_to is not None for s in stats),
        "upgrade_rate": round(sum(s.upgraded_to is not None for s in stats) / n, 3) if n else None,
        "broadcast_only_excluded": broadcasts,
    }


def weekly_trend(stats: list[ConversationStats]) -> list[dict[str, Any]]:
    weeks: dict[str, list[ConversationStats]] = {}
    for s in stats:
        day = parse(s.first_message_at)
        monday = (day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")
        weeks.setdefault(monday, []).append(s)
    return [{"week": w, **{k: v for k, v in summary(items).items() if k != "broadcast_only_excluded"}}
            for w, items in sorted(weeks.items())]


def by_agent(stats: list[ConversationStats]) -> list[dict[str, Any]]:
    agents: dict[str, list[float]] = {}
    for s in stats:
        if s.agent and s.first_response_min is not None:
            agents.setdefault(s.agent, []).append(s.first_response_min)
    rows = [{"agent": a, "first_replies": len(t), "median_first_response_min": percentile(t, 50),
             "p90_first_response_min": percentile(t, 90)} for a, t in agents.items()]
    return sorted(rows, key=lambda r: -r["first_replies"])


def broadcast_count(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM (SELECT conversation_id FROM messages GROUP BY conversation_id "
                           "HAVING SUM(sender = 'member') = 0)").fetchone()[0])


def as_dicts(stats: list[ConversationStats]) -> list[dict[str, Any]]:
    return [asdict(s) for s in stats]
