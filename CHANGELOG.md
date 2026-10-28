# Changelog

## 2.1.0

- **Live webhook** `POST /api/webhook/message`: one message or a list per call, members created on first sight,
  idempotent on redelivery, an optional `automated` flag from the platform, and an n8n workflow template.
- **Fairness:** agents, topics and plans with fewer than 10 contacts are flagged as too few to compare; the rules
  are documented in METRICS.md.
- Member email is optional (chats and DMs often have none); updates never blank out a known name or email.
- Validation errors never echo submitted data.

## 2.0.0

- **Contacts:** threads are split into contacts when a member returns after a reply and a quiet gap.
- **Business-hours response time** with the team's time zone, working days and holidays.
- **SLA** compliance and breaches, including unanswered contacts; **open queue** with alerts.
- **Topics** (Arabic + English keyword taxonomy), per-agent and per-plan breakdowns.
- **Funnel and revenue:** upgrades within the window and the monthly revenue they added; plan names and prices configurable.
- **Bring your own data:** CSV import with line-level validation, JSON import, API-key push endpoint with size limits,
  scheduled sync, sync status and watermark.
- **Metric evaluation:** 14 exact scenarios (79 checks) and invariants on 25 random datasets, gated in CI.
- Spreadsheet-safe CSV export, security headers, redesigned dashboard.
- Package reorganized into `core`, `ingest`, `analytics`, `api` and `eval`; tests mirror the package.

## 1.0.0

- Bot filtering, human-only first response, reply rate, waiting on reply, upgrades after support, dashboard.
