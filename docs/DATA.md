# Bringing your own data

The tool works with any community platform, helpdesk or chat tool that can export conversations.
You need two files (a third is optional); [`examples/csv/`](../examples/csv) has a working sample.

## CSV import

```bash
python -m support_analytics sync --csv ./my-export
```

| File | Columns |
|---|---|
| `members.csv` | `id, name, email, joined_at` |
| `messages.csv` | `id, conversation_id, member_id, sender (member\|agent), agent_name, body, sent_at` |
| `subscriptions.csv` (optional) | `member_id, tier, status (active\|trial\|canceled\|past_due\|expired), started_at` |

- Timestamps are ISO-8601 **with an offset** (`2026-10-04T10:00:00+03:00` or `...Z`).
- `conversation_id` groups messages of one thread (a DM, chat or ticket).
- One row per plan change in `subscriptions.csv`; plan names are yours (set their order and prices in the config).
- Every row is validated; the first invalid row stops the import and reports its file and line.
- Re-importing is safe: rows are upserted by id, nothing is ever deleted.

JSON works too (`--json export.json` with `members`, `messages`, `subscriptions` arrays of the same fields).

## Push API

For live data, push batches from your platform's webhooks or a small script:

```bash
export SA_API_KEYS='["a-long-random-key"]'
curl -X POST http://localhost:8000/api/ingest \
  -H "X-API-Key: a-long-random-key" -H "Content-Type: application/json" \
  -d @batch.json
```

- Keys are compared in constant time; the endpoint is disabled when no key is configured.
- Payloads are size-limited (`SA_MAX_INGEST_BYTES`, default 5 MB) and fully validated.
- Messages must refer to members that exist in the store or in the same batch.
- `GET /api/sync/status` returns the latest runs and a **watermark** (newest message time) so a pusher
  can send only what is new.

## Scheduled sync

```bash
SA_SYNC_SOURCE=csv:/data/exports SA_SYNC_INTERVAL_S=900 uvicorn support_analytics.api.app:app
```

The API re-imports the source every 15 minutes. Failed runs are logged in `sync_runs` and retried next time.

## Configuration

Copy [`workspace.example.json`](../workspace.example.json), adjust business hours, holidays, SLA, topics,
plan order and prices, and point `SA_CONFIG_PATH` at it.
