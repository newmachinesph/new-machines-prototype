---
name: extract-leads
description: Write one lead and one sheet row per enquiry email.
---

`emails` holds the enquiry emails; `screening` holds one item per email checked, `{ref, answers}`, where `ref` is the email's `messageId` and `answers.urgency.value` is `urgent`, `soon` or `normal`.

For each email, in order:

- `thread_id`: its `threadId`.
- `received`: the date part (YYYY-MM-DD) of `messageTimestamp`.
- `name`: the name in `sender` (before the `<address>`); when there is none, the part of the address before `@`.
- `email`: the address in `sender`.
- `company`: a company the sender names for themselves, in brackets (such as `(Okafor Legal)`) or after their name in the sign-off (such as `Maya Chen, Brightleaf Events`); otherwise `Not given`.
- `request`: the email's `subject`, at most 200 characters.
- `urgency`: from the screening item with the same `ref`; `normal` when there is none.

`rows` has one row per lead, every cell text: `[received, name, company, email, request, urgency, thread_id]`.
