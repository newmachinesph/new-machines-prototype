---
name: classify-orders
description: Follow each order across the business app's four sections and give every break one kind and one action.
---

Start from the ledger. For every sales order in `sales_orders` (the list is under `sales_orders`), find by the same `id`: the store order in `orders`, its store payments in `payments` (by `order_id`), the served order in `served_orders` and the sale in `sales`. Find the customer in `customers` by `customer_id`; its `payment_terms_days` wins over the sales order's when they differ.

Then:

- `reference_date` is the sales order's invoice date (the calendar date in UTC); for an order not shipped it is the store order's order date.
- `due_date` is the invoice date plus the customer's payment terms. `delivered_on` is the day the warehouse delivered the order (`delivered_at`), or null. `days_outstanding` is the whole days from the reference date to `as_of`.
- A store payment is pending when its `status` is `pending`. An order is paid when the sales order's `balance` is 0 or its `paid` is true.
- An order is delivered when the sales order's `delivered` is true or the served order's `delivered` is true. It is released when a served order exists and its `released` is true.
- The account manager is the customer's `account_manager` and `account_manager_email` when the ledger records them; otherwise the sale's `seller_name` and `seller_email`; otherwise the store order's `seller_email` with no name; otherwise null for both.

Give each order the first kind that fits, in this order. One order gets one exception at most.

| kind | When | recommended_action |
|---|---|---|
| `disputed` | The balance is above 0 and the customer's `notes` mention a dispute or a credit memo. | `escalate_finance` |
| `payment_pending_confirmation` | The balance is above 0 and a pending store payment exists for the order. | `confirm_payment` |
| `shipped_not_paid` | The order is delivered, the balance is above 0 and `days_outstanding` is more than the payment terms plus `grace_days`. | `draft_collection_message`, or `escalate_finance` when the customer has no email |
| `paid_not_shipped` | The order is paid, not delivered, and either no served order exists or it is not released, and at least 1 day has passed since the order date. | `nudge_warehouse` after more than 2 working days, otherwise `none` |

An order that fits none of these is clean, a delivered invoice still inside its terms or grace included. Count it in `clean_count` and do not list it.

Fill the exception like this:

- `amount_minor`: the balance in centavos; for `paid_not_shipped`, the paid total in centavos.
- `customer_email`: from the customer record, else `null`. `invoice_number`: the sales order's.
- `evidence`: one short sentence, about 40 words at most, naming only the sections that disagree and what each shows, with dates and peso amounts. Do not repeat the other fields of the exception in it. For example `The warehouse delivered DEMO-SNP-2 on 2026-09-17 and ledger invoice INV-2026-0003 (15-day terms) still shows the full balance of ₱12,480.00, 16 days past due.` For a balance above ₱20,000, add that finance's sign-off is needed before any message.
- Never include email addresses, phone numbers or customer message text in a `note` or `flag`.

Order the exceptions by kind in the table's order (`paid_not_shipped` first, `disputed` last), then by `days_outstanding`, longest first.

Totals: per kind, the count and the sum of `amount_minor` of its exceptions; `currency` is `PHP`.

`sign_off_note`: one sentence naming each `shipped_not_paid` order whose balance is above ₱20,000 with its amount, such as `DEMO-SNP-1 (₱40,252.80) is above ₱20,000 and needs finance's sign-off before its reminder goes out.`; an empty string when there is none.

A sales order with no usable date (neither a valid `invoice_date` nor `created_at`, or an `order_date` that is not a date) cannot be aged: leave it out of the checks (it is neither an exception nor clean) and name its id at the end of the summary as skipped.

The summary is two or three sentences: orders checked across the business app's four sections, how many are clean, and the count and peso total per kind found, pending payments first.
