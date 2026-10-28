"""Small groups are shown but flagged, so nobody is judged on a handful of contacts."""
from datetime import UTC, datetime

from support_analytics.analytics.contacts import compute_contacts
from support_analytics.analytics.reports import MIN_FAIR_SAMPLE, by_agent, by_topic
from support_analytics.core.config import WorkspaceConfig
from support_analytics.ingest.store import connect

NOW = datetime(2026, 10, 23, 18, tzinfo=UTC)


def test_small_groups_are_flagged(demo_db) -> None:
    contacts = compute_contacts(connect(demo_db), WorkspaceConfig(), now=NOW)
    for rows in (by_agent(contacts), by_agent(contacts[:40]), by_topic(contacts[:40])):
        assert all(r["low_sample"] == (r["contacts"] < MIN_FAIR_SAMPLE) for r in rows)
    assert any(r["low_sample"] for r in by_agent(contacts[:40]))
