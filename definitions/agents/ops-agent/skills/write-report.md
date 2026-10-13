---
name: write-report
description: Turn resolved mismatches into sheet rows and a short summary.
---

Build one row for every matched order and every mismatch, in this column order:

`[date, order_id, kind, amount, status, note]`

- `date`: the `date` from the match result (`YYYY-MM-DD`).
- `order_id`: the order name such as `#1004`. For a payment with no order, use the charge id.
- `kind`: `matched`, or the mismatch kind (`missing_payment`, `missing_order`, `amount_mismatch`, `currency_mismatch`, `duplicate`).
- `amount`: the amount as a decimal string in major units with two places, for example `89.66`. Convert from minor units. For `amount_mismatch`, use the order total.
- `status`: `matched` for matched rows. For a mismatch use `resolved` when the reviewer explained it, `open` when the reviewer left it open, and `unreviewed` when there is no reviewer decision for it.
- `note`: for matched rows leave it empty (`""`). For mismatches, the reviewer's note if there is one, otherwise the explanation from the match result.

Put mismatches after the matched rows, ordered by date.

Totals:

- `orders_count`, `matched_count` and `mismatch_count` come from the match result totals. Do not recount them differently.
- `net_difference_minor` is the sum of `amount_diff_minor` over all mismatches.
- `currency` is the currency of the match result.

Summary: say how many orders were checked, how many matched, how many mismatches there were and how they were handled, and the net difference as a signed amount with its currency. Name the orders that are still open.
