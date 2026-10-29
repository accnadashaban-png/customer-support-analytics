# Connect your own support data

Four ways in, from easiest to most live. Every one ends in the same validated tables, so every metric rule,
test and fairness flag applies unchanged. Re-running any of them is safe: nothing is duplicated, nothing is deleted.

| Your situation | Use | Live? |
|---|---|---|
| You can export chats or tickets to CSV or JSON, in **any** layout | A **mapping file** (below) | Re-run or schedule it |
| Your helpdesk or chat data is in a database you can read | A **read-only database connection** (below) | Scheduled sync |
| Your website chat, WhatsApp or DMs can call a URL per message | The **webhook** ([LIVE.md](LIVE.md)) | Instant |
| You prefer our own three-file layout | `sync --csv folder` ([DATA.md](DATA.md)) | Re-run |

## 1. Any export, with a mapping file

You describe your columns once; your export is never edited.

```bash
python -m support_analytics sync --file helpdesk-export.csv --mapping helpdesk-mapping.json
```

[`examples/connect/helpdesk-mapping.json`](../examples/connect/helpdesk-mapping.json):

```json
{
  "format": "csv",
  "fields": {
    "conversation_id": "Ticket ID",   "member_id": "Customer ID",   "member_name": "Customer",
    "email": "Customer Email",        "sender": "Author Type",      "agent_name": "Agent",
    "body": "Message",                "sent_at": "Created At",      "automated": "Automated"
  },
  "sender_values": {"member": ["customer"], "agent": ["agent"]},
  "timezone": "Africa/Cairo",
  "time_format": "%Y-%m-%d %H:%M"
}
```

- **Required columns:** conversation, customer, sender, text and time. Message id, agent name, customer name,
  email and an "automated" flag are optional; a stable message id is generated when you have none.
- **Who wrote it:** `sender_values` lists how your export spells a customer and a team member. An unknown value
  stops the import with the row number instead of guessing.
- **Time:** ISO-8601 with or without an offset, epoch seconds or milliseconds, or any `time_format`. Times without an
  offset are read in `timezone` and stored in UTC.
- **Nested JSON** (most chat platforms): set `"format": "json"`, point `records` at the list
  (`"data.messages"`) and use dotted names (`"from.role"`). See
  [`chat-export.json`](../examples/connect/chat-export.json) with [`chat-mapping.json`](../examples/connect/chat-mapping.json).
- **Plans (optional):** `subscriptions_file` and `subscription_fields` add plan changes for the upgrade metrics;
  `status_values` maps your status names (`"active": ["paid"]`).

## 2. Your database, read-only

```bash
pip install -e ".[postgres]"     # only for PostgreSQL; SQLite needs nothing
python -m support_analytics sync --sql database-connection.json
```

[`examples/connect/database-connection.json`](../examples/connect/database-connection.json) holds the URL and one
`SELECT` per table, written against **your** schema and returning our column names:

```sql
SELECT r.id AS id, t.id AS conversation_id, t.customer_id AS member_id, c.full_name AS member_name,
       CASE WHEN r.author_kind = 'staff' THEN 'agent' ELSE 'member' END AS sender,
       r.author_name AS agent_name, r.content AS body, r.created_at AS sent_at, r.is_bot AS automated
FROM replies r JOIN tickets t ON t.id = r.ticket_id JOIN customers c ON c.id = t.customer_id
```

Safety, in layers:

1. Only one `SELECT` (or `WITH ... SELECT`) is accepted; anything that writes or changes settings is refused.
2. The connection itself is read-only: SQLite files are opened with `mode=ro`, PostgreSQL sessions use read-only
   transactions. Use a database user that can only read (`GRANT SELECT`).
3. Rows are capped, and the connection file can live outside the project (it holds a password for PostgreSQL).

**Live:** run it on a schedule inside the dashboard service:

```bash
SA_SYNC_SOURCE="sql:/secure/path/database-connection.json" SA_SYNC_INTERVAL_S=300 uvicorn support_analytics.api.app:app
```

The same works for an export that another job refreshes: `SA_SYNC_SOURCE="mapped:/data/chats.csv|/data/mapping.json"`.
