# Customer Support Analytics

[![CI](https://github.com/accnadashaban-png/customer-support-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/accnadashaban-png/customer-support-analytics/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

Turns a support inbox into numbers a team can act on: **how fast humans reply, how many members are still waiting, and who upgraded after talking to support.** It filters out bots and broadcasts, normalizes every timestamp to UTC, syncs idempotently, and serves a filterable dashboard.

![Dashboard: KPIs, weekly trend, agents, and a conversation with an automated message marked as not counted](docs/dashboard.jpg)

> A public, from-scratch rebuild of an internal tool I built end to end at work, running on **synthetic data** (fictional members, messages and subscriptions) so the code can be shared. No company data, names or integrations.

## Why accuracy needs rules

Raw inbox exports make support look better or worse than it is. The metrics here follow explicit rules, each covered by a test with a hand-computed answer:

| Rule | Why |
|---|---|
| **Bots never count as a reply.** Verification codes, welcome messages and renewal reminders sent from the support account are detected (`bot_patterns.txt`, case- and whitespace-insensitive, English and Arabic) and excluded. | Otherwise an auto-message 20 seconds after the member writes looks like a 20-second response. |
| **First response = member's first message → first *human* reply after it.** | Measures what the member actually experienced. |
| **Broadcast-only threads are excluded.** A thread where the member never wrote isn't a support conversation. | Mass reminders would inflate the volume and deflate the reply rate. |
| **Waiting on reply** = the latest message from a person is the member's, with no human reply after it. A lone "thanks" / "شكرًا" / "تمام" doesn't need an answer. | Gives the team a real to-do list, without false alarms. |
| **Upgrade after support** = moved to a higher paid tier within 14 days of the first message. A `trial` counts as paid access; cancellations and downgrades don't count. | Connects support work to revenue without counting churn as success. |
| **Everything is stored in UTC** and shown in the viewer's local time. Naive timestamps are rejected. | Date filters and durations are exact across timezones. |
| **Sync is an upsert and never deletes.** Re-running it changes nothing; an empty or failed pull leaves the data intact; every run is logged in `sync_runs`. | Safe to schedule; history only grows. |

## Metrics

- Median and p90 first response time (nearest-rank percentiles), plus mean
- Reply rate, conversations waiting on a reply
- Upgrades after support and upgrade rate
- Weekly trend and per-agent breakdown

## Quick start

```bash
pip install -e ".[dev]"
python -m support_analytics sync            # load demo data (run it twice: nothing changes)
python -m support_analytics report --days 30
uvicorn support_analytics.api:app           # dashboard on http://127.0.0.1:8000
pytest                                       # 19 tests, 91% coverage
```

Or with Docker: `docker build -t customer-support-analytics . && docker run -p 8000:8000 customer-support-analytics`

## Plugging in a real source

A source returns three validated lists (`Member`, `Message`, `Subscription`; see `models.py`). `JsonSource` reads an export file:

```bash
python -m support_analytics sync --json export.json
```

For a live helpdesk or community platform, write a small adapter with a `fetch()` method that returns the same `Batch`; validation, bot filtering, UTC normalization and idempotent storage are handled for you.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/summary?days=30` | KPIs for a period (or `start` / `end`) |
| GET | `/api/conversations?view=last30\|waiting\|upgraded\|all&tier=&q=` | Filterable, searchable list |
| GET | `/api/conversations/{id}` | Transcript with automated messages flagged |
| GET | `/api/trend`, `/api/agents` | Weekly trend, per-agent stats |
| POST | `/api/sync` | Run a sync |
| GET | `/health` | Liveness |

## Project layout

```
support_analytics/
  models.py         validated records (Pydantic), tier order, access rules
  classify.py       automated-message detection
  bot_patterns.txt  editable patterns (English + Arabic)
  db.py             schema, UTC normalization, idempotent upsert, sync log
  metrics.py        per-conversation stats, summary, trend, agents
  sources.py        Source protocol, JSON export source, synthetic generator
  api.py            FastAPI service
web/index.html      dashboard (KPIs, trend chart, agents, filters, transcript drawer)
tests/              exact-answer metric tests + API tests
```

## Related

- [Case study: Support analytics dashboard](https://github.com/accnadashaban-png/work-case-studies#4-support-analytics-dashboard)
- [bilingual-market-assistant](https://github.com/accnadashaban-png/bilingual-market-assistant): Arabic + English AI assistant with safe text-to-SQL

---

Built by [Nada Shaban](https://nadashaaban.com) · MIT License
