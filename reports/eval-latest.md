# Metric evaluation

Generated 2026-10-28 16:51.

**Scenarios:** 14/14 passed (79 exact checks)  
**Invariants:** 25/25 synthetic datasets passed (127 contacts each on average)

| Scenario | Rule | Result |
|---|---|---|
| `bot-is-not-a-reply` | An automated verification code 30 seconds after the member writes is not the first response. | pass |
| `after-hours-counts-business-time` | Thursday 17:50 to Sunday 09:10 is 63h20m on the calendar but 20 business minutes (Sun-Thu 09:00-18:00). | pass |
| `unanswered-breaches-sla-and-alerts` | An unanswered contact breaches the SLA once its business age passes the target, and is in the alert queue. | pass |
| `unanswered-inside-sla-is-not-yet-a-breach` | Unanswered for 30 business minutes with a 60-minute target: waiting, not breached, no alert. | pass |
| `returning-member-is-a-new-contact` | The member comes back two days after a reply: a second contact with its own response time. | pass |
| `follow-up-inside-the-gap-stays-one-contact` | A new question 20 minutes after a reply is the same contact, and it is waiting again. | pass |
| `closing-thanks-needs-no-reply` | A lone thank-you after the answer does not put the contact back in the queue (English and Arabic). | pass |
| `broadcast-only-threads-are-excluded` | A renewal reminder nobody answered is not a support contact. | pass |
| `upgrade-to-trial-counts-with-revenue` | Basic to Pro trial five days after the contact is an upgrade worth 29 - 9 = 20 per month. | pass |
| `downgrade-cancel-and-late-upgrade-are-not-upgrades` | A downgrade, a cancellation, and an upgrade after the 14-day window never count. | pass |
| `team-time-zone-is-respected` | Dubai team (UTC+4): a message at 08:30 local answered at 09:30 local is 60 calendar but 30 business minutes. | pass |
| `holidays-are-not-business-time` | Sunday is a holiday: a Sunday 10:00 message answered Monday 10:00 took 60 business minutes. | pass |
| `first-human-agent-gets-the-credit` | The first human reply is credited, not later ones. | pass |
| `local-time-input-is-normalized` | Timestamps sent with a +03:00 offset are stored and measured in UTC. | pass |

## Invariant failures

None.
