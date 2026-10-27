# Customer Support Analytics

[![CI](https://github.com/accnadashaban-png/customer-support-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/accnadashaban-png/customer-support-analytics/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![Metric eval](https://img.shields.io/badge/metric%20eval-14%20scenarios%20%C2%B7%2025%20datasets-success) ![License](https://img.shields.io/badge/license-MIT-green)

Support analytics for any community, helpdesk or chat team: **who is still waiting for an answer, how fast your team really replies in business hours, whether you meet your SLA, what people ask about, and who upgraded after talking to support.** Bring your own data as CSV or JSON, or push it through an API.

![Dashboard: KPIs, the open queue sorted by business-time waiting, and the support funnel](docs/dashboard.jpg)

> A public, from-scratch rebuild of an internal tool I built end to end at work, running here on **synthetic data**. No company data, names or integrations.

## What it answers

| Question | How |
|---|---|
| Who is waiting for us right now? | An **open queue**, oldest first, with waiting time in business hours and alerts past a threshold. |
| How fast do we reply, honestly? | First response to each **contact**, in calendar and **business** minutes (team time zone, working days, holidays). Bots never count as a reply. |
| Do we meet our SLA? | Share of contacts answered within the target, and every breach, including unanswered ones. |
| What do people ask about? | Arabic + English **topic** classification with per-topic reply rate, speed and SLA. |
| Does support drive revenue? | Upgrades within 14 days of a contact, the **monthly revenue** they added, and a contacted → replied → within SLA → upgraded **funnel**. |
| Who on the team carries the load? | Per-agent first replies, speed and SLA. |

## Why the numbers can be trusted

Raw exports make support look better or worse than it is. The rules are explicit ([METRICS.md](docs/METRICS.md)) and **evaluated**:

- **14 exact scenarios** (79 checks), one rule each, computed by hand: a bot code 30 seconds after the member writes,
  Thursday-evening-to-Sunday replies (63 h on the clock, 20 business minutes), holidays, a team in another time zone,
  a returning member starting a second contact, a lone "thanks", trials, downgrades, cancellations, late upgrades, offsets in input timestamps.
- **Invariants on 25 random datasets**: business time never exceeds calendar time, a met SLA is within target,
  upgrades are inside the window and go up a plan, re-importing the same data changes nothing.
- The evaluator is tested too: a deliberately wrong expectation must fail.

```bash
python -m support_analytics eval     # scenarios 14/14 (79 checks), invariants 25/25
```

## Quick start

```bash
pip install -e ".[dev]"
python -m support_analytics sync                    # demo data (run it twice: nothing changes)
uvicorn support_analytics.api.app:app               # dashboard on http://127.0.0.1:8000
pytest                                              # 38 tests
```

**Your own data:** `python -m support_analytics sync --csv ./my-export` with the three CSVs described in [DATA.md](docs/DATA.md)
([sample](examples/csv)). Adjust business hours, holidays, SLA, topics and plan prices with
[`workspace.example.json`](workspace.example.json) and `SA_CONFIG_PATH`.

**Live data:** push batches to `POST /api/ingest` with an API key, or let the API re-import a folder on a schedule.

**Docker:** `docker build -t customer-support-analytics . && docker run -p 8000:8000 customer-support-analytics`

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/kpis?days=30` | Contacts, reply rate, median/p90 response (calendar and business), SLA, waiting, upgrades, MRR |
| GET | `/api/queue` | Open contacts, oldest first, with alert flags |
| GET | `/api/contacts?view=last30\|waiting\|breached\|upgraded\|all&topic=&tier=&q=` | Filterable list |
| GET | `/api/contacts.csv` | Same filters as CSV (spreadsheet-safe) |
| GET | `/api/contacts/{id}` | Transcript with automated messages flagged |
| GET | `/api/trend` · `/api/funnel` · `/api/breakdown/{topics\|agents\|tiers}` | Charts and breakdowns |
| POST | `/api/ingest` · `/api/sync` | Push data · run the configured source (API key required) |
| GET | `/api/sync/status` · `/api/config` · `/health` | Last runs and watermark · active configuration · liveness |

## Security

- The ingest and sync endpoints are **off unless API keys are configured**; keys are compared in constant time.
- Payload size limits and full validation; messages must refer to known members.
- **CSV export is protected against formula injection** (cells starting with `=`, `+`, `-`, `@` are escaped).
- Sync is an upsert that **never deletes**; failed runs roll back and are recorded.
- Security headers on every response; CORS is closed unless origins are configured.

## Project layout

```
support_analytics/
  core/        settings (env), workspace config (business hours, SLA, topics, prices)
  ingest/      models, CSV/JSON/synthetic sources, bot detection, idempotent store, sync + scheduler
  analytics/   contacts, business hours, reports (KPIs, queue, trend, breakdowns, funnel)
  api/         FastAPI app
  eval/        exact scenarios + invariants runner
web/           dashboard
tests/         mirrors the package: analytics/ ingest/ api/ eval/
docs/          metric definitions, data formats
examples/csv/  a working sample export
```

## Related

- [Case study: Support analytics dashboard](https://github.com/accnadashaban-png/work-case-studies#4-support-analytics-dashboard)
- [bilingual-market-assistant](https://github.com/accnadashaban-png/bilingual-market-assistant): Arabic + English AI assistant with safe text-to-SQL

---

Built by [Nada Shaban](https://nadashaaban.com) · MIT License
