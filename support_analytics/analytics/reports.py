"""Aggregations over contacts: KPIs, queue, trend, agents, topics, funnel and revenue."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from support_analytics.analytics.contacts import Contact, parse


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(pct / 100 * len(ordered))) - 1]


def in_range(contacts: list[Contact], start: datetime | None, end: datetime | None) -> list[Contact]:
    return [c for c in contacts if (start is None or parse(c.first_message_at) >= start)
            and (end is None or parse(c.first_message_at) < end)]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def kpis(contacts: list[Contact]) -> dict[str, Any]:
    n = len(contacts)
    cal = [c.first_response_min for c in contacts if c.first_response_min is not None]
    bus = [c.first_response_business_min for c in contacts if c.first_response_business_min is not None]
    judged = [c for c in contacts if c.sla_met is not None or c.sla_breached]
    return {
        "contacts": n,
        "replied": sum(c.replied for c in contacts),
        "reply_rate": _rate(sum(c.replied for c in contacts), n),
        "median_first_response_min": percentile(cal, 50),
        "p90_first_response_min": percentile(cal, 90),
        "median_first_response_business_min": percentile(bus, 50),
        "p90_first_response_business_min": percentile(bus, 90),
        "sla_met_rate": _rate(sum(1 for c in judged if c.sla_met and not c.sla_breached), len(judged)),
        "sla_breaches": sum(c.sla_breached for c in contacts),
        "waiting_on_reply": sum(c.waiting for c in contacts),
        "upgrades": sum(c.upgraded_to is not None for c in contacts),
        "upgrade_rate": _rate(sum(c.upgraded_to is not None for c in contacts), n),
        "mrr_from_upgrades": round(sum(c.mrr_gain for c in contacts), 2),
    }


def queue(contacts: list[Contact], alert_after_minutes: int) -> list[dict[str, Any]]:
    """Open contacts nobody has answered yet, oldest first, with an alert flag."""
    rows = [c for c in contacts if c.waiting]
    rows.sort(key=lambda c: c.waiting_since or "")
    return [{"contact_id": c.contact_id, "member_name": c.member_name, "email": c.email, "topic": c.topic,
             "waiting_since": c.waiting_since, "waiting_business_min": c.waiting_business_min,
             "first_message": c.first_message, "current_tier": c.current_tier,
             "alert": (c.waiting_business_min or 0) > alert_after_minutes} for c in rows]


def trend(contacts: list[Contact]) -> list[dict[str, Any]]:
    weeks: dict[str, list[Contact]] = defaultdict(list)
    for c in contacts:
        day = parse(c.first_message_at)
        weeks[(day - timedelta(days=day.weekday())).strftime("%Y-%m-%d")].append(c)
    keep = ("contacts", "reply_rate", "median_first_response_min", "median_first_response_business_min", "sla_met_rate")
    return [{"week": w, **{k: v for k, v in kpis(items).items() if k in keep}} for w, items in sorted(weeks.items())]


MIN_FAIR_SAMPLE = 10  # below this, a person's or topic's numbers are mostly chance; show them, but don't rank on them


def _grouped(contacts: list[Contact], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[Contact]] = defaultdict(list)
    for c in contacts:
        value = getattr(c, key)
        if value:
            groups[value].append(c)
    rows = [{key: k, **{m: v for m, v in kpis(items).items() if m in (
        "contacts", "replied", "reply_rate", "median_first_response_business_min", "sla_met_rate", "upgrades")},
        "low_sample": len(items) < MIN_FAIR_SAMPLE}
        for k, items in groups.items()]
    return sorted(rows, key=lambda r: (-r["contacts"], r[key]))


def by_agent(contacts: list[Contact]) -> list[dict[str, Any]]:
    return _grouped([c for c in contacts if c.agent], "agent")


def by_topic(contacts: list[Contact]) -> list[dict[str, Any]]:
    return _grouped(contacts, "topic")


def by_tier(contacts: list[Contact]) -> list[dict[str, Any]]:
    return _grouped(contacts, "tier_at_contact")


def funnel(contacts: list[Contact]) -> list[dict[str, Any]]:
    steps = [("contacted", len(contacts)), ("replied", sum(c.replied for c in contacts)),
             ("replied within SLA", sum(1 for c in contacts if c.sla_met)),
             ("upgraded", sum(c.upgraded_to is not None for c in contacts))]
    top = steps[0][1] or 1
    return [{"step": s, "count": n, "share": round(n / top, 3)} for s, n in steps]
