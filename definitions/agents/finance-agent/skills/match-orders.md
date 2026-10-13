---
name: match-orders
description: Pair each order with the payment that settled it.
---

Pair orders with payments in this order of preference. Use each payment at most once.

1. **By reference.** A payment whose metadata order id, description or reference names the order (for example `#1004`) belongs to that order.
2. **By amount and date.** For orders still unpaired, look for an unpaired payment with the same currency and an amount equal to the order total (within the rounding tolerance in the company knowledge) created within 2 days of the order date. If exactly one payment fits, pair them. If several fit, do not guess: leave the order unmatched and say why in the explanation.

Before comparing:

- Order totals are decimal strings in major units; payment amounts are integers in minor units. Convert to minor units first (`"45.00"` is 4500).
- Compare currencies case-insensitively (`USD` and `usd` are the same).
- Dates are the calendar date of the creation time in UTC.

After pairing:

- A pair whose amounts are equal (within tolerance) and whose currencies agree is **matched**.
- A pair with a different amount or currency is a mismatch (see `explain-mismatch`).
- An order left without a payment is a mismatch of kind `missing_payment`.
- A payment left without an order is a mismatch of kind `missing_order`.
- Two payments for one order are a mismatch of kind `duplicate`: pair the first, report the extra.
- A refunded or negative payment is explained by the company knowledge on refunds; use it before reporting.
