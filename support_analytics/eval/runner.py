"""Metric evaluation.

1. Scenarios (`scenarios/scenarios.json`): small, hand-computed cases, one rule each. Every expected field
   must match exactly.
2. Invariants: properties that must hold for any data, checked on many seeded synthetic datasets
   (for example: business time never exceeds calendar time, a met SLA is within target, re-syncing changes nothing).

    python -m support_analytics eval
Exits with code 1 on any failure (used as a CI gate) and writes reports/eval-latest.md.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from support_analytics.analytics import reports
from support_analytics.analytics.contacts import Contact, broadcast_threads, compute_contacts, parse
from support_analytics.core.config import WorkspaceConfig
from support_analytics.core.settings import ROOT
from support_analytics.ingest.classify import AutomationClassifier
from support_analytics.ingest.models import Member, Message, Subscription, tier_rank
from support_analytics.ingest.sources import SyntheticSource
from support_analytics.ingest.store import connect, upsert
from support_analytics.ingest.sync import sync

SCENARIOS = Path(__file__).parent / "scenarios" / "scenarios.json"
BASE_CONFIG = {"business_hours": {"timezone": "UTC"}}


def _merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in extra.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _load(con: sqlite3.Connection, scenario: dict[str, Any]) -> None:
    ids = {m[1] for m in scenario["messages"]} | {s[0] for s in scenario.get("subscriptions", [])}
    members = [Member(id=i, name=i, email=f"{i}@example.com", joined_at="2026-01-01T00:00:00Z") for i in sorted(ids)]
    messages = [Message(id=f"msg{n}", conversation_id=c, member_id=m, sender=s, agent_name=a, body=b, sent_at=t)
                for n, (c, m, s, a, b, t) in enumerate(scenario["messages"])]
    subs = [Subscription(member_id=m, tier=tier, status=st, started_at=t) for m, tier, st, t in scenario.get("subscriptions", [])]
    upsert(con, members, messages, subs, AutomationClassifier())


def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    cfg = WorkspaceConfig.model_validate(_merge(BASE_CONFIG, scenario.get("config", {})))
    con = connect(":memory:")
    _load(con, scenario)
    contacts = {c.contact_id: c for c in compute_contacts(con, cfg, now=parse(scenario["now"]))}
    failures: list[str] = []
    checks = 0
    if set(scenario["expect"]) != set(contacts):
        failures.append(f"contacts: expected {sorted(scenario['expect'])}, got {sorted(contacts)}")
    for cid, fields in scenario["expect"].items():
        for field, want in fields.items():
            checks += 1
            got = getattr(contacts[cid], field) if cid in contacts else "<missing>"
            if got != want:
                failures.append(f"{cid}.{field}: expected {want!r}, got {got!r}")
    if "expect_kpis" in scenario:
        k = reports.kpis(list(contacts.values()))
        for field, want in scenario["expect_kpis"].items():
            checks += 1
            if k[field] != want:
                failures.append(f"kpis.{field}: expected {want!r}, got {k[field]!r}")
    if "expect_queue" in scenario:
        checks += 1
        q = [{"contact_id": r["contact_id"], "alert": r["alert"]} for r in reports.queue(list(contacts.values()), cfg.alert_after_minutes)]
        if q != scenario["expect_queue"]:
            failures.append(f"queue: expected {scenario['expect_queue']}, got {q}")
    if "expect_broadcasts" in scenario:
        checks += 1
        if broadcast_threads(con) != scenario["expect_broadcasts"]:
            failures.append("broadcast count mismatch")
    return {"id": scenario["id"], "rule": scenario["rule"], "checks": checks, "passed": not failures, "failures": failures}


def invariant_violations(contacts: list[Contact], cfg: WorkspaceConfig) -> list[str]:
    bad: list[str] = []
    for c in contacts:
        if c.replied and c.first_response_business_min is not None and c.first_response_min is not None \
                and c.first_response_business_min > c.first_response_min + 0.1:
            bad.append(f"{c.contact_id}: business time exceeds calendar time")
        if c.sla_met and c.first_response_business_min is not None and c.first_response_business_min > cfg.sla_first_response_minutes:
            bad.append(f"{c.contact_id}: SLA met above target")
        if c.sla_met and c.sla_breached:
            bad.append(f"{c.contact_id}: SLA both met and breached")
        if c.replied and c.first_response_min is not None and c.first_response_min <= 0:
            bad.append(f"{c.contact_id}: non-positive first response")
        if c.upgraded_to and (c.days_to_upgrade is None or c.days_to_upgrade > cfg.upgrade_window_days
                              or tier_rank(c.upgraded_to, cfg.tier_order) <= tier_rank(c.tier_at_contact, cfg.tier_order)):
            bad.append(f"{c.contact_id}: invalid upgrade")
        if c.waiting and c.waiting_since and parse(c.waiting_since) < parse(c.first_message_at):
            bad.append(f"{c.contact_id}: waiting before the contact started")
    k = reports.kpis(contacts)
    if k["reply_rate"] is not None and not 0 <= k["reply_rate"] <= 1:
        bad.append("reply rate outside [0, 1]")
    if k["median_first_response_min"] is not None and k["median_first_response_min"] > k["p90_first_response_min"]:
        bad.append("median above p90")
    return bad


def run_invariants(seeds: range = range(1, 26)) -> list[dict[str, Any]]:
    cfg = WorkspaceConfig()
    out = []
    for seed in seeds:
        con = connect(":memory:")
        sync(con, SyntheticSource(seed=seed, members=120, days=60))
        now = parse(con.execute("SELECT MAX(sent_at) FROM messages").fetchone()[0])
        first = compute_contacts(con, cfg, now=now)
        bad = invariant_violations(first, cfg)
        sync(con, SyntheticSource(seed=seed, members=120, days=60))  # re-sync must change nothing
        if [vars(c) for c in compute_contacts(con, cfg, now=now)] != [vars(c) for c in first]:
            bad.append("re-sync changed the metrics")
        out.append({"seed": seed, "contacts": len(first), "passed": not bad, "violations": bad[:5]})
    return out


def main(report: Path = ROOT / "reports" / "eval-latest") -> int:
    scenarios = [run_scenario(s) for s in json.loads(SCENARIOS.read_text(encoding="utf-8"))]
    invariants = run_invariants()
    s_ok = sum(r["passed"] for r in scenarios)
    i_ok = sum(r["passed"] for r in invariants)
    checks = sum(r["checks"] for r in scenarios)
    lines = ["# Metric evaluation", "", f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}.", "",
             f"**Scenarios:** {s_ok}/{len(scenarios)} passed ({checks} exact checks)  ",
             f"**Invariants:** {i_ok}/{len(invariants)} synthetic datasets passed "
             f"({statistics.fmean(r['contacts'] for r in invariants):.0f} contacts each on average)", "",
             "| Scenario | Rule | Result |", "|---|---|---|"]
    lines += [f"| `{r['id']}` | {r['rule']} | {'pass' if r['passed'] else 'FAIL: ' + '; '.join(r['failures'])} |" for r in scenarios]
    failed = [r for r in invariants if not r["passed"]]
    lines += ["", "## Invariant failures", ""] + ([f"- seed {r['seed']}: {r['violations']}" for r in failed] or ["None."])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"scenarios {s_ok}/{len(scenarios)} ({checks} checks), invariants {i_ok}/{len(invariants)}")
    for r in scenarios:
        if not r["passed"]:
            print("FAIL", r["id"], r["failures"])
    for r in failed:
        print("INVARIANT", r["seed"], r["violations"])
    return 0 if s_ok == len(scenarios) and i_ok == len(invariants) else 1


if __name__ == "__main__":
    raise SystemExit(main())
