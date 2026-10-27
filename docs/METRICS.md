# Metric definitions

Every definition below is enforced by an exact scenario in
[`support_analytics/eval/scenarios/scenarios.json`](../support_analytics/eval/scenarios/scenarios.json).

## Contacts

A **contact** is one request from a member. A thread (DM, chat or ticket) can hold several contacts:
a new contact starts when the member writes again **after the team replied and the thread was quiet for
`contact_gap_hours`** (default 12). Measuring whole threads would hide slow replies to returning members.

Threads where the member never wrote (broadcasts, reminders) are **not** contacts and are reported separately.

## Response time

| Metric | Definition |
|---|---|
| First response (calendar) | From the contact's first member message to the first **human** reply after it. |
| First response (business) | The same interval counted only inside business hours, in the team's time zone, skipping non-working days and holidays. |
| Automated messages | Messages matching `ingest/bot_patterns.txt` (verification codes, welcomes, reminders; English and Arabic, case- and whitespace-insensitive) are never a reply. |
| Agent credit | The agent who sent the first human reply. |
| Median / p90 | Nearest-rank percentiles over replied contacts. |

Example: a message on Thursday 17:50 answered on Sunday 09:10 (team works Sunday to Thursday, 09:00-18:00)
took 63 h 20 min on the calendar and **20 business minutes**.

## SLA

- **Met:** first response within `sla_first_response_minutes` business minutes (default 60).
- **Breached:** answered later than the target, or still unanswered after the target.
- An unanswered contact that is still inside the target is neither met nor breached yet.

## Queue and alerts

- **Waiting:** the latest message from a person is the member's, and it is not just a closing phrase
  ("thanks", "شكرًا", "تمام"... configurable).
- The **open queue** lists waiting contacts, oldest first, with their waiting time in business hours.
- **Alert:** waiting longer than `alert_after_minutes` business minutes (default 120).

## Topics

The contact's first message is matched against a keyword taxonomy (English and Arabic, configurable).
Topics are checked in order, so more specific ones come first ("cancel my subscription" is a cancellation,
not a plan question). Anything unmatched is `other`.

## Upgrades and revenue

- **Upgrade after support:** a plan higher in `tier_order` starts within `upgrade_window_days` (default 14)
  after the contact. A `trial` counts as paid access; cancellations and downgrades never count.
- **MRR from upgrades:** `monthly_price[new plan] - monthly_price[plan at contact]`.
- **Funnel:** contacted → replied → replied within SLA → upgraded.

## Time

All timestamps are stored in UTC; inputs with an offset are converted, inputs without one are rejected.
The dashboard shows times in the viewer's local time zone; business-time maths uses the team's time zone.
