"""Split support threads into contacts and compute everything about each contact.

A thread with one member can stay open for weeks. Each time the member comes back after the
team replied and the thread went quiet for `contact_gap_hours`, that is a new contact with its
own first response time. Measuring the whole thread as one conversation would hide slow replies
to returning members.

Rules (each one has an exact test scenario in support_analytics/eval/scenarios):
- Only threads where the member wrote are support contacts; broadcast-only threads are excluded.
- Automated messages (verification codes, welcomes, reminders) never count as a reply.
- First response = first human reply after the contact's first member message, in calendar
  minutes and in business minutes (team time zone, working days, holidays).
- SLA met = first response within the target business minutes. An unanswered contact breaches
  the SLA once its business-time age passes the target.
- Waiting = the latest message from a person is the member's and is not just a closing phrase.
- Upgrade = a higher paid plan starts within the window after the contact; trial counts as paid.
- Topic = scored over all the member's messages in the contact, "uncertain" when no topic is clearly ahead.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from support_analytics.analytics.business_hours import business_minutes
from support_analytics.analytics.topics import GREETING_OR_CLOSING, classify, normalize
from support_analytics.core.config import WorkspaceConfig
from support_analytics.ingest.models import has_access, tier_rank


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Contact:
    contact_id: str
    conversation_id: str
    member_id: str
    member_name: str
    email: str
    first_message_at: str
    last_message_at: str
    messages: int
    first_message: str
    topic: str
    topic_confidence: float  # 0.5 (a tie) to 1.0; see analytics/topics.py
    replied: bool
    first_response_min: float | None
    first_response_business_min: float | None
    agent: str | None
    sla_met: bool | None  # None while unanswered and still inside the SLA
    sla_breached: bool
    waiting: bool
    waiting_since: str | None
    waiting_business_min: float | None
    tier_at_contact: str
    current_tier: str
    upgraded_to: str | None
    days_to_upgrade: float | None
    mrr_gain: float


def _is_closing(body: str, phrases: list[str]) -> bool:
    text = re.sub(r"[\s!.,?؟🙏❤️]+", " ", body.lower()).strip()
    return text in {p.lower() for p in phrases}


def classify_topic(text: str, topics: dict[str, list[str]]) -> str:
    """One message's topic (the contact uses all its member messages: see analytics/topics.py)."""
    return classify([text], topics).topic


def _tier_at(subs: list[sqlite3.Row], moment: datetime) -> str:
    current = "Free"
    for s in subs:  # sorted by started_at
        if parse(s["started_at"]) <= moment:
            current = s["tier"] if has_access(s["status"]) else "Free"
    return current


def split_contacts(msgs: list[sqlite3.Row], gap: timedelta) -> list[list[sqlite3.Row]]:
    """A new contact starts when the member writes after a human reply and a quiet gap."""
    groups: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    answered = False
    for m in msgs:
        if current and m["sender"] == "member" and answered and parse(m["sent_at"]) - parse(current[-1]["sent_at"]) >= gap:
            groups.append(current)
            current, answered = [], False
        current.append(m)
        if m["sender"] == "agent" and not m["is_automated"] and any(x["sender"] == "member" for x in current):
            answered = True
    if current:
        groups.append(current)
    return groups


def compute_contacts(con: sqlite3.Connection, cfg: WorkspaceConfig, now: datetime | None = None) -> list[Contact]:
    now = now or datetime.now(UTC)
    members = {r["id"]: r for r in con.execute("SELECT id, name, email FROM members")}
    subs: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute("SELECT member_id, tier, status, started_at FROM subscriptions ORDER BY started_at"):
        subs.setdefault(r["member_id"], []).append(r)
    threads: dict[str, list[sqlite3.Row]] = {}
    for r in con.execute("SELECT conversation_id, member_id, sender, agent_name, body, sent_at, is_automated "
                         "FROM messages ORDER BY sent_at, id"):
        threads.setdefault(r["conversation_id"], []).append(r)

    gap = timedelta(hours=cfg.contact_gap_hours)
    hours = cfg.business_hours
    out: list[Contact] = []
    for cid, msgs in threads.items():
        for n, group in enumerate(split_contacts(msgs, gap)):
            member_msgs = [m for m in group if m["sender"] == "member"]
            if not member_msgs:
                continue  # broadcast-only: not a support contact
            first_at = parse(member_msgs[0]["sent_at"])
            human = [m for m in group if m["sender"] == "agent" and not m["is_automated"]]
            reply = next((m for m in human if parse(m["sent_at"]) > first_at), None)
            calendar = round((parse(reply["sent_at"]) - first_at).total_seconds() / 60, 1) if reply else None
            business = business_minutes(first_at, parse(reply["sent_at"]), hours) if reply else None

            people = [m for m in group if m["sender"] == "member" or not m["is_automated"]]
            waiting_since = None
            if people[-1]["sender"] == "member":
                last_human = max((parse(m["sent_at"]) for m in human), default=None)
                open_msgs = [m for m in member_msgs if last_human is None or parse(m["sent_at"]) > last_human]
                if not all(_is_closing(m["body"], cfg.closing_phrases) for m in open_msgs):
                    waiting_since = open_msgs[0]["sent_at"]
            waiting_age = business_minutes(parse(waiting_since), now, hours) if waiting_since else None
            unanswered_age = business_minutes(first_at, now, hours) if not reply else None

            member_subs = subs.get(member_msgs[0]["member_id"], [])
            at_contact = _tier_at(member_subs, first_at)
            upgrade = next((s for s in member_subs
                            if first_at < parse(s["started_at"]) <= first_at + timedelta(days=cfg.upgrade_window_days)
                            and has_access(s["status"])
                            and tier_rank(s["tier"], cfg.tier_order) > tier_rank(at_contact, cfg.tier_order)), None)
            gain = (cfg.monthly_price.get(upgrade["tier"], 0) - cfg.monthly_price.get(at_contact, 0)) if upgrade else 0.0
            member = members.get(member_msgs[0]["member_id"])
            topic = classify([m["body"] for m in member_msgs], cfg.topics, cfg.topic_min_ratio)
            out.append(Contact(
                contact_id=f"{cid}#{n + 1}", conversation_id=cid, member_id=member_msgs[0]["member_id"],
                member_name=member["name"] if member else member_msgs[0]["member_id"], email=member["email"] if member else "",
                first_message_at=iso(first_at), last_message_at=group[-1]["sent_at"], messages=len(group),
                first_message=next((m["body"] for m in member_msgs if not GREETING_OR_CLOSING.match(normalize(m["body"]))),
                                   member_msgs[0]["body"])[:200], topic=topic.topic, topic_confidence=topic.confidence,
                replied=reply is not None, first_response_min=calendar, first_response_business_min=business,
                agent=reply["agent_name"] if reply else None,
                sla_met=(business <= cfg.sla_first_response_minutes) if business is not None else None,
                sla_breached=(business is not None and business > cfg.sla_first_response_minutes)
                or (unanswered_age is not None and unanswered_age > cfg.sla_first_response_minutes),
                waiting=waiting_since is not None, waiting_since=waiting_since, waiting_business_min=waiting_age,
                tier_at_contact=at_contact, current_tier=_tier_at(member_subs, now),
                upgraded_to=upgrade["tier"] if upgrade else None,
                days_to_upgrade=round((parse(upgrade["started_at"]) - first_at).total_seconds() / 86400, 1) if upgrade else None,
                mrr_gain=round(gain, 2),
            ))
    return out


def broadcast_threads(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM (SELECT conversation_id FROM messages GROUP BY conversation_id "
                           "HAVING SUM(CASE WHEN sender = 'member' THEN 1 ELSE 0 END) = 0) AS b").fetchone()[0])


def as_dicts(contacts: list[Contact]) -> list[dict[str, Any]]:
    return [asdict(c) for c in contacts]
