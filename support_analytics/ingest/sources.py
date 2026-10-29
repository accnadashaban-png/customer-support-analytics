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
# The demo business: Wasla, a fictional home-internet provider (plans Free = prepaid, Basic 50 Mbps,
# Pro 200 Mbps, Elite 1 Gbps), with a support team of 8 answering WhatsApp, web chat and email in one inbox.
AGENTS = ["Sara", "Omar", "Mona", "Youssef", "Hana", "Karim", "Laila", "Tamer"]
FIRST_NAMES = ["Ahmed", "Fatma", "Khaled", "Nour", "Hassan", "Laila", "Tarek", "Huda", "Karim", "Salma", "Ali", "Rana",
               "Mostafa", "Dina", "Yara", "Amr", "Mariam", "Hany", "Reem", "Ziad", "Omnia", "Sherif", "Nada", "Bassem",
               "Aya", "Hossam", "Menna", "Walid", "Shahd", "Adham"]
LAST_NAMES = ["Adel", "Farouk", "Samir", "Lotfy", "Nabil", "Fathy", "Ramzy", "Gamal", "Sabry", "Zaki", "Hegazy", "Shawky",
              "Mansour", "Ezzat", "Badawy"]
QUESTIONS = {  # what Wasla's customers ask, by topic (a returning customer follows up on the same topic)
    "connection": ["My internet has been down since this morning", "النت فاصل عندي من امبارح", "The connection drops every evening",
                   "النت بطيء جدا بالليل", "Speed test shows 20 Mbps on a 200 plan", "el net bey2ta3 kol shwaya",
                   "الانترنت مقطوع في المنطقة؟"],
    "device": ["The router shows a red light", "الراوتر فيه لمبة حمرا", "How do I change the wifi password?",
               "عايز اغير اسم الواي فاي", "Wifi doesn't reach the second floor", "الراوتر بيعيد تشغيل نفسه"],
    "billing": ["Why is this month's bill higher?", "الفاتورة جاية زيادة ليه؟", "I was charged twice this month", "اتخصم مني مرتين",
                "Can I get last month's invoice?", "ازاي ادفع الفاتورة من الابلكيشن؟", "I paid but the app still says unpaid"],
    "plans": ["How much is the Elite plan?", "الباقة الأسرع بكام؟", "I want to upgrade to a faster plan", "عايز ارقي باقتي",
              "Is there a student discount?", "في عروض على الباقات؟", "What's the difference between Pro and Elite?"],
    "installation": ["When will the technician come?", "الفني هييجي امتى يركب الخط؟", "I'm moving, can you move my line?",
                     "عايز انقل الخط لعنوان جديد", "The technician missed the appointment"],
    "account": ["I can't log in to the app", "نسيت باسورد الابلكيشن", "The verification code never arrives", "عايز اغير الايميل"],
    "cancellation": ["How do I cancel my subscription?", "عايز الغي الاشتراك", "Please end my contract next month",
                     "ازاي الغي التجديد التلقائي"],
}
TOPIC_WEIGHTS = {"connection": 26, "device": 14, "billing": 18, "plans": 16, "installation": 10, "account": 9, "cancellation": 7}
FOLLOW_UPS = ["Any update?", "Still waiting on this", "في جديد؟", "لسه مستني رد"]
OPENERS = ["Hi", "Hello", "السلام عليكم", "مساء الخير", "Good morning"]  # sometimes the first message is only a greeting
REPLIES = {  # the team's answers, by topic
    "connection": ["There's maintenance in your area; service is back by 6 pm.", "I've reset your line from our side, please try now.",
                   "تم إعادة ضبط الخط من عندنا، جرّب دلوقتي."],
    "device": ["Please restart the router; if the light stays red I'll send a replacement.", "You can change it from the app under Wi-Fi.",
               "هبعتلك راوتر جديد خلال يومين."],
    "billing": ["I've refunded the extra charge; it will show in 3-5 days.", "Sure, I've sent the invoice to your email.",
                "الفاتورة فيها رسوم التركيب لأول شهر بس."],
    "plans": ["The Elite plan is 79 USD a month, and you can upgrade from the app.", "Students get 20% off with a valid ID.",
              "تقدر ترقي من الأبلكيشن والسرعة الجديدة تشتغل فورًا."],
    "installation": ["I've booked a technician visit for tomorrow between 10 and 2.", "Your move is scheduled for Sunday.",
                     "تمام، الفني هيكلمك قبل ما يوصل."],
    "account": ["I've reset your password; check your email.", "The code is on its way; it can take a minute.",
                "تم تحديث الإيميل على حسابك."],
    "cancellation": ["Done. Your line stays active until the end of the month.", "I've turned off auto-renewal for you.",
                     "تم الإلغاء، والخدمة شغالة لآخر الشهر."],
}
AUTOMATED = ["Your verification code is {code}", "Welcome to Wasla! Your line is now active.",
             "Your membership renews on {date}.", "Reminder: your technician visit is tomorrow."]


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
    """Seeded generator for the demo business (Wasla): customers, support chats with bots, greetings, broadcasts,
    returning customers and plan changes. 5,000 customers over 12 months by default."""

    def __init__(self, seed: int = 7, members: int = 5000, end: datetime = datetime(2026, 10, 23, 18, tzinfo=UTC),
                 days: int = 365):
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
                topic = rng.choices(list(TOPIC_WEIGHTS), weights=list(TOPIC_WEIGHTS.values()))[0]
                if rng.random() < 0.15:  # "Hi" first, the real question a minute later
                    batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(OPENERS), at, seq))
                    at += timedelta(minutes=1)
                    seq += 1
                if rng.random() < 0.3:  # an automated message arrives right after the member writes
                    batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS[topic]), at, seq))
                    at += timedelta(seconds=20)
                    seq += 1
                    batch.messages.append(self._msg(cid, mid, "agent", "Sara", rng.choice(AUTOMATED), at, seq))
                else:
                    batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS[topic]), at, seq))
                seq += 1
                last = at
                recent = at > self.end - timedelta(days=3)
                if rng.random() < (0.85 if recent else 0.999):  # a few recent contacts are still open; almost no old one is forgotten
                    reply_at = self._reply_at(at)
                    if reply_at < self.end:
                        batch.messages.append(self._msg(cid, mid, "agent", rng.choice(AGENTS), rng.choice(REPLIES[topic]),
                                                        reply_at, seq))
                        seq += 1
                        last = reply_at
                        if rng.random() < 0.35:
                            follow = reply_at + timedelta(minutes=rng.randint(2, 600))
                            if follow < self.end:
                                batch.messages.append(self._msg(cid, mid, "member", None, "Thanks!", follow, seq))
                                seq += 1  # every message needs its own id
                                last = follow
                if rng.random() < 0.25:  # the member comes back days later in the same thread: a new contact
                    back = last + timedelta(days=rng.uniform(1, 6))  # always after the conversation so far
                    if back < self.end - timedelta(hours=2):
                        batch.messages.append(self._msg(cid, mid, "member", None, rng.choice(QUESTIONS[topic] + FOLLOW_UPS), back,
                                                        seq))
                        seq += 1
                        if rng.random() < (0.85 if back > self.end - timedelta(days=3) else 0.999):
                            again = self._reply_at(back)
                            if again < self.end:
                                batch.messages.append(self._msg(cid, mid, "agent", rng.choice(AGENTS), rng.choice(REPLIES[topic]),
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
