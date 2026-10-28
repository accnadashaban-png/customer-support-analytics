# Connect a live source

Send each chat or DM message to the dashboard as it happens, so the open queue and response times are always current.

## 1. Turn on the API key

```bash
export SA_API_KEYS=a-long-random-key          # several keys: comma-separated, e.g. one per sender
uvicorn support_analytics.api.app:app
```

Without a key, all write endpoints stay closed (`403`).

## 2. Send messages

`POST /api/webhook/message` with the header `X-API-Key`. The body is one message, or a list of up to 500:

```json
{
  "message_id": "msg-9001",
  "conversation_id": "dm-thread-42",
  "sender": "member",
  "body": "Hi, I can't log in",
  "sent_at": "2026-10-22T08:00:00Z",
  "member": {"id": "customer-17", "name": "Salma", "email": ""}
}
```

| Field | Notes |
|---|---|
| `sender` | `member` (the customer) or `agent` (your team). |
| `agent_name` | Required for agent messages, unless `automated` is `true`. |
| `automated` | Optional. `true` for auto-replies when your platform knows it; otherwise automatic messages are detected from the text. |
| `sent_at` | Must include a time zone (`Z` or `+02:00`). |
| `member` | Only `id` is required. A new member is created on first sight; later messages may send the id alone. Email is optional. |

```bash
curl -X POST http://127.0.0.1:8000/api/webhook/message \
  -H "X-API-Key: $SA_API_KEYS" -H "Content-Type: application/json" \
  -d '{"message_id":"msg-9001","conversation_id":"dm-thread-42","sender":"member","body":"Hi","sent_at":"2026-10-22T08:00:00Z","member":{"id":"customer-17"}}'
```

Senders retry webhooks, so delivering the same `message_id` again changes nothing.

## 3. Where messages come from

- **Website chat:** call the endpoint from your **server** when a chat message is saved. Never put the API key in
  browser code, where anyone can read it.
- **DMs and chat platforms:** most send their own webhooks. Point them at an automation tool such as n8n, map the
  fields, and forward. [`examples/n8n/forward-support-messages.json`](../examples/n8n/forward-support-messages.json)
  is a ready workflow: import it, set `SUPPORT_ANALYTICS_URL`, add a Header Auth credential named `X-API-Key`,
  and adjust the field names in the mapping step.
- **Exports and back-fills:** use `POST /api/ingest` for members, messages and subscriptions in bulk, or
  `python -m support_analytics sync --csv ./folder`.

## Errors

| Code | Meaning |
|---|---|
| `401` | Missing or wrong key. |
| `403` | No keys configured: writes are disabled. |
| `413` | Body larger than `SA_MAX_INGEST_BYTES`, or more than 500 messages. |
| `422` | Invalid message. The response names the field but never repeats what was sent, since it can hold personal data. |
