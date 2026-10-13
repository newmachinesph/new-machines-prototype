---
name: apply-refund-policy
description: Propose approve, partial or decline for each request, and write the reply and review item.
---

Apply the refund policy in the company knowledge. The usual policy is, checked in this order:

1. No matching order: `decline`, amount 0.
2. The request repeats an earlier request for the same order: `decline`, amount 0.
3. The payment is already refunded: `decline`, amount 0.
4. The customer says the item was opened or used (the whole word `opened` or `used` appears in the email; `unused` does not count): `partial`, amount = half of the requested amount (at most the order total), rounded down to the cent.
5. Otherwise: `approve`, amount = the requested amount, at most the order total.

If the company knowledge says something different, follow it and say so in the reason.

**Case** `{thread_id, from, order_id, charge_id, requested_minor, currency, recommendation, amount_minor, reason}`. The currency is the order's, or `USD` when there is no order. The reason is one sentence, such as `The customer says the item was opened or used, so the refund is partial: 50% of the amount asked for.`

**Reply message** `{to, about, facts, ref}`, one per case:

- `to`: the case's `from`. `about`: `Your refund request for order <number>`, using the number the customer gave.
- `ref`: the same `ref` as the case's review item (below), so a reviewer's note reaches the right reply. The order number the customer gave goes in `about` and the first fact, not here.
- `facts`, in this order:
  1. `Order number: <number>` (the number the customer gave, or `not given`)
  2. `Requested refund: <amount> <CURRENCY>`
  3. `Proposed decision: <approve the full refund of <amount> <CURRENCY> | refund 50% (<amount> <CURRENCY>) | decline the refund>` with the reason in plain words
  4. `This decision is proposed and a member of our team will confirm it. No refund has been issued yet.`

**Review item** `{ref, date, amount_minor, currency, flag, note, counterpart_ref?}`:

- `ref`: the order number the customer gave. Use the `thread_id` instead when they gave none or when the request repeats an earlier one, so every review item has its own `ref`. `date`: the request date.
- `amount_minor`: the requested amount. `flag`: `Proposed: approve`, `Proposed: partial 50%` or `Proposed: decline`.
- `note`: the case's reason. `counterpart_ref`: the charge id; leave it out when there is none.
- Never include email addresses, phone numbers or customer message text in a `note` or `flag`.

The summary is one or two sentences: requests triaged, and how many are proposed for approve, partial and decline. Say that no refund has been issued.
