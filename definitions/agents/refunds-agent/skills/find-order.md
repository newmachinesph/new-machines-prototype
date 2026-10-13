---
name: find-order
description: Link each refund request to its order and payment.
---

Each item in `threads` (the list is under `messages`) is one refund request. Work through them oldest first, by `messageTimestamp`, and write the cases in that order.

- `thread_id`: the email's `threadId`.
- `from`: the sender's email address only, without the display name (`Priya Nair <priya.nair@example.com>` gives `priya.nair@example.com`).
- The request date is the calendar date (UTC) of `messageTimestamp`.
- The order number is the first `#` followed by digits in the subject or the text, for example `#1003`.
- The requested amount is the first dollar amount in the subject or the text, in minor units (`$23.50` is 2350). If no amount is given, use the order total.

Then look the order up in `orders` (the list is under `orders`) by its `name`, for example `#1003`:

- No order with that name, or no order number in the email: `order_id` is null and `charge_id` is null.
- Otherwise `order_id` is the order name, and its total is `total_price` in minor units (`"23.50"` is 2350).

Find the payment in `charges` (the list is under `data`): the charge whose `metadata.order_id` or `description` names the order. Its `id` is the `charge_id`; null when there is none. The payment is already refunded when the charge has `refunded: true` or `amount_refunded` of at least its `amount`, or when the order's `financial_status` is `refunded`.

A request repeats an earlier one when an earlier request (by `messageTimestamp`) names the same order number.
