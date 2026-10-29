# Changelog

## 2.3.0

- **Connect any export as it is:** a JSON mapping file names your columns, how your export spells customer and
  agent, and your time zone; CSV or nested JSON (dotted paths), ISO, epoch or custom timestamps, generated message
  ids, optional plan changes. Errors name the row. `sync --file chats.csv --mapping map.json`.
- **Connect your database, read-only:** one SELECT per table against your own schema; single-SELECT check, SQLite
  opened with `mode=ro`, PostgreSQL read-only transactions, a row cap. `sync --sql connection.json`, optional
  `postgres` extra.
- Both work on a schedule inside the API (`SA_SYNC_SOURCE=mapped:...` or `sql:...`) for a live view.
- Examples in `examples/connect/` (helpdesk CSV, chat-platform JSON, database connection) and docs/CONNECT.md.
- 61 tests.

## 2.2.0

- **Topic classification you can trust:** scored over every member message of a contact (not only the first),
  Arabic normalization with dialect prefixes and suffixes, weighted keywords, a confidence per contact, and
  "uncertain" when no topic is clearly ahead. Measured on 176 hand-labeled contacts: 90.9% accuracy on the unseen
  half (tuned on the other half only), 100% precision on 6 of 7 topics; CI fails below 90%.
- **Bigger demo business, Wasla** (fictional home-internet provider): 5,000 customers over 12 months, 8 agents,
  Arabic dialects, English and Franco, greetings before the question, same-topic follow-ups, replies that match the
  question. Fixed in the generator: a reused message id could overwrite a message, and a follow-up could be dated
  before the reply; both are now tested.
- The open queue shows the first message that says something, not "Hi".
- **New look:** navy and cyan, light and dark with a switch, phone layout.
- README: database diagram and real sample rows; METRICS: how topics are decided and measured.
- 51 tests.

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
