---
name: plan-follow-ups
description: Decide which meetings need a follow-up and plan one message per outside guest.
---

`events` is a calendar list: `items` holds the events in time order. For each event, add one entry to `meetings` (`event_id` is the event's `id`, `title` its `summary`, `start` its `start.dateTime` or `start.date`):

1. A cancelled event (`status` is `cancelled`) needs no follow-up: reason `The meeting was cancelled.`
2. If no attendee is marked `self`, the event has no guests outside the team. Otherwise its guests are the attendees who are not `self`, whose email domain differs from the `self` attendee's domain, and whose `responseStatus` is not `declined`. With no guests: reason `Nobody outside your team took part.`
3. Otherwise it needs a follow-up: reason `Follow up with 1 person outside your team.` for one guest, otherwise `Follow up with N people outside your team.`

For each guest of a meeting that needs a follow-up, plan one message:

- `to`: the guest's email.
- `about`: `Follow-up: <title>` (at most 150 characters).
- `facts`, in order:
  - `Thank you for the meeting "<title>" on <day>.`
  - each line of the event's `description` that starts with `Agreed:`, unchanged;
  - when there is no such line, `Please let me know if anything from the meeting needs a follow-up.`
- `ref`: `<event id>:<guest email>`.

Never include anything from the description other than its `Agreed:` lines.
