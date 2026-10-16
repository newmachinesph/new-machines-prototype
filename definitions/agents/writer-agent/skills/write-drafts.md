---
name: write-drafts
description: Turn each message item into one email draft.
---

For every item in `items`, write one draft with these fields:

- `to`: the item's `to`, unchanged.
- `subject`: the item's `about`, unchanged (at most 150 characters).
- `body`: plain text, in this order:
  1. A greeting line: `Hello,`
  2. The facts, each as one plain sentence, in the order given.
  3. A short closing line that fits the tone, such as asking the customer to reply with any questions.
  4. The sign-off on its own lines: `Kind regards,` then the `sign_off` input when there is one, otherwise `Accounts team`.
- `ref`: the item's `ref`, unchanged. Only when the item has no `ref`, take it from the first fact (for example `Invoice number: INV-0107` gives `INV-0107`).

Reviewer input:

- `review` is null when nobody reviewed the items. Otherwise it has an overall `note` and a list of `resolutions`, each naming a record (`order_id` holds the record's `ref`, the same `ref` as one of the items) with the reviewer's call and note.
- Apply the overall note to every draft, and a resolution's note to the draft with the same `ref`.
- Still write exactly one draft per item: a person decides which drafts to send.
- Never include email addresses, phone numbers or customer message text in a `note` or `flag`.

Keep each body under 4000 characters. Do not add attachments, links or placeholders such as `[name]`.
