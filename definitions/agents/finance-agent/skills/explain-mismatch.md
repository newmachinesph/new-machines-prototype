---
name: explain-mismatch
description: Classify a mismatch and explain it in one sentence.
---

Give every mismatch one `kind`:

| kind | When |
|---|---|
| `missing_payment` | The order has no payment. |
| `missing_order` | The payment has no order. |
| `amount_mismatch` | Order and payment are paired but the amounts differ by more than the rounding tolerance. |
| `currency_mismatch` | Order and payment are paired but the currencies differ. |
| `duplicate` | The order has more than one payment; this is the extra one. |

Fill the fields like this:

- `order_id` and `charge_id`: the ids from the input. Use `null` for the side that does not exist.
- `date`: the order date, or the payment date when there is no order.
- `amount_minor`: the order total in minor units, or the payment amount when there is no order.
- `amount_diff_minor`: the payment amount minus the order total, in minor units, with its sign. A payment that is short is negative. With no payment, the difference is minus the order total. With no order, it is the payment amount.
- `explanation`: one sentence. State what differs and the most likely reason only if the input supports it (for example a fee that matches the company knowledge). If the cause is unknown, say that it is unknown.

Example: "Order #1004 was paid 2.90 USD less than its total, which is consistent with the card fee on a gross-reporting merchant." Do not add anything that the order, the payment or the company knowledge does not show.
