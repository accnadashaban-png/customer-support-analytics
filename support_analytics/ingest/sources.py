"""Data sources. A source returns validated members, messages and subscriptions.

`SyntheticSource` generates realistic, fully fictional support data for the demo.
`JsonSource` reads an export file, which is how a real helpdesk or community
platform would plug in: write an adapter that returns the same three lists.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from support_analytics.ingest.models import TIERS, Member, Message, Subscription

LOCAL = timezone(timedelta(hours=3))  # the source reports local time; storage normalizes to UTC
AGENTS = ["Sara", "Omar", "Mona", "Youssef"]
FIRST_NAMES = ["Ahmed", "Fatma", "Khaled", "Nour", "Hassan", "Laila", "Tarek", "Huda", "Karim", "Salma", "Ali", "Rana",
               "Mostafa", "Dina", "Yara", "Amr", "Mariam", "Hany", "Reem", "Ziad"]
LAST_NAMES = ["Adel", "Farouk", "Samir", "Lotfy", "Nabil", "Fathy", "Ramzy", "Gamal", "Sabry", "Zaki"]
QUESTIONS = ["Hi, I can't log in to my account", "How do I join the live session?", "I paid but my plan didn't change",
             "What's the difference between Pro and Elite?", "Can I get an invoice?", "السلام عليكم، عايز أرقّي اشتراكي",
             "الفيديو مش بيشتغل عندي", "ممكن أعرف مواعيد اللايف؟", "Is there a student discount?", "How do I cancel?"]
REPLIES = ["Thanks for reaching out! Let me check that for you.", "Done, please try again now.",
           "Here's the link with all the details.", "أهلا بيك! تم حل المشكلة، جرّب تاني.", "Sure, I've sent it to your email."]
AUTOMATED = ["Your verification code is {code}", "Welcome to the community! Start here: ...",
             "Your membership renews on {date}.", "Reminder: live session starts in 1 hour."]


@dataclass
class Batch:
    members: list[Member] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.members or self.messages or self.subscriptions)


class Source(Protocol):
    def fetch(self) -> Batch: ...


class JsonSource:
    def __init__(self, path: Path):
        self.path = path

    def fetch(self) -> Batch:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return Batch([Member.model_validate(m) for m in data.get("members", [])],
                     [Message.model_validate(m) for m in data.get("messages", [])],
                     [Subscription.model_validate(s) for s in data.get("subscriptions", [])])


class CsvSource:
    """Bring your own data as three CSV files in one folder (UTF-8, ISO-8601 timestamps with a UTC offset):

    members.csv        id, name, email, joined_at
    messages.csv       id, conversation_id, member_id, sender (member|agent), agent_name, body, sent_at
    subscriptions.csv  member_id, tier, status (active|trial|canceled|past_due|expired), started_at

    subscriptions.csv is optional. Every row is validated; the first bad row stops the import with its line number.
    """

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _rows(self, name: str, model: type[BaseModel], required: bool = True) -> list[Any]:
        import csv

        path = self.folder / name
        if not path.exists():
            if required:
                raise FileNotFoundError(f"missing {path}")
            return []
        out = []
        with path.open(encoding="utf-8-sig", newline="") as f:
            for line, row in enumerate(csv.DictReader(f), start=2):
                clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
                if "agent_name" in clean and not clean["agent_name"]:
                    clean["agent_name"] = None
                try:
                    out.append(model.model_validate(clean))
                except Exception as exc:
                    raise ValueError(f"{name} line {line}: {exc}") from exc
        return out

    def fetch(self) -> Batch:
        return Batch(self._rows("members.csv", Member), self._rows("messages.csv", Message),
                     self._rows("subscriptions.csv", Subscription, required=False))


class SyntheticSource:
    """Seeded generator: members, support DMs (with bots and broadcasts), and tier changes."""

    def __init__(self, seed: int = 7, members: int = 450, end: datetime = datetime(2026, 10, 23, 18, tzinfo=UTC),
                 days: int = 120):
        self.rng, self.n, self.end, self.days = random.Random(seed), members, end, days

    def _reply_delay(self, at: datetime) -> timedelta:
        """Faster during the day, slower at night, with a long tail."""
        hour = at.astimezone(LOCAL).hour
        base = 25 if 9 <= hour < 18 else (90 if 18 <= hour < 23 else 420)
        return timedelta(minutes=max(1.0, self.rng.lognormvariate(0, 0.9) * base))

    def _reply_at(self, at: datetime) -> datetime:
        """When the team replies: most replies land in working hours (Sun-Thu 09:00-18:00 local)."""
        reply = at + self._reply_delay(at)
        local = reply.astimezone(LOCAL)
        off_hours = local.weekday() in (4, 5) or not 9 <= local.hour < 18  # Friday/Saturday or outside 9-18
        if off_hours and self.rng.random() < 0.8:
            day = local.date() + timedelta(days=1 if local.hour >= 18 else 0)
            while day.weekday() in (4, 5):
                day += timedelta(days=1)
            opening = datetime(day.year, day.month, day.day, 9, tzinfo=LOCAL)
            reply = max(reply, opening) + timedelta(minutes=self.rng.uniform(3, 90))
        return reply

    def fetch(self) -> Batch:
        rng, batch = self.rng, Batch()
        start = self.end - timedelta(days=self.days)
        for i in range(self.n):
            mid = f"m{i:04d}"
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            joined = start - timedelta(days=rng.randint(1, 400))
            batch.members.append(Member(id=mid, name=name, email=f"{name.split()[0].lower()}.{i}@example.com",
                                        joined_at=joined.astimezone(LOCAL)))
            tier = rng.choices(TIERS, weights=[45, 25, 20, 10])[0]
            status = "trial" if tier != "Free" and rng.random() < 0.15 else "active"
            batch.subscriptions.append(Subscription(member_id=mid, tier=tier, status=status, started_at=joined))

            if rng.random() < 0.25:  # renewal reminder nobody answered: broadcast-only
                at = start + timedelta(minutes=rng.randint(0, self.days * 1440))
                batch.messages.append(self._msg(f"b{i}", mid, "agent", None, rng.choice(AUTOMATED), at, 0))

            for c in range(rng.choices([0, 1, 2, 3], weights=[35, 45, 15, 5])[0]):
                cid = f"c{i:04d}_{c}"
                at = start + timedelta(minutes=rng.randint(0, self.days * 1440 - 60))
                if at > self.end - timedelta(hours=1):
                    continue
                seq = 0
                if rng.random() < 0.3:  # an automated message arrives right after the member writes
                    batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS), at, seq))
                    at += timedelta(seconds=20)
                    seq += 1
                    batch.messages.append(self._msg(cid, mid, "agent", "Sara", rng.choice(AUTOMATED), at, seq))
                else:
                    batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS), at, seq))
                seq += 1
                if rng.random() < 0.9:  # 10% are still unanswered
                    reply_at = self._reply_at(at)
                    if reply_at < self.end:
                        batch.messages.append(self._msg(cid, mid, "agent", rng.choice(AGENTS), rng.choice(REPLIES),
                                                        reply_at, seq))
                        seq += 1
                        if rng.random() < 0.35:
                            follow = reply_at + timedelta(minutes=rng.randint(2, 600))
                            if follow < self.end:
                                batch.messages.append(self._msg(cid, mid, "member", None, "Thanks!", follow, seq))
                if rng.random() < 0.25:  # the member comes back days later in the same thread: a new contact
                    back = at + timedelta(days=rng.uniform(1, 6))
                    if back < self.end - timedelta(hours=2):
                        batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS), back, seq))
                        seq += 1
                        if rng.random() < 0.85:
                            again = self._reply_at(back)
                            if again < self.end:
                                batch.messages.append(self._msg(cid, mid, "agent", rng.choice(AGENTS), rng.choice(REPLIES),
                                                                again, seq))
                                seq += 1
                if rng.random() < 0.16 and tier != "Elite":  # upgrade after support
                    higher = TIERS[TIERS.index(tier) + 1:]
                    up_at = at + timedelta(days=rng.uniform(0.2, 25))
                    if up_at < self.end:
                        batch.subscriptions.append(Subscription(member_id=mid, tier=rng.choice(higher),
                                                                status=rng.choice(["active", "trial"]), started_at=up_at))
                        tier = batch.subscriptions[-1].tier
                elif rng.random() < 0.05 and tier != "Free":  # some cancel instead
                    end_at = at + timedelta(days=rng.uniform(1, 20))
                    if end_at < self.end:
                        batch.subscriptions.append(Subscription(member_id=mid, tier=tier, status="canceled", started_at=end_at))
        return batch

    def _msg(self, cid: str, mid: str, sender: str, agent: str | None, body: str, at: datetime, seq: int) -> Message:
        body = body.format(code=self.rng.randint(100000, 999999), date="2026-11-01")
        return Message(id=f"{cid}_{seq}", conversation_id=cid, member_id=mid, sender=sender,  # type: ignore[arg-type]
                       agent_name=agent if sender == "agent" else None, body=body, sent_at=at.astimezone(LOCAL))


__all__ = ["UTC", "Batch", "JsonSource", "Source", "SyntheticSource"]
