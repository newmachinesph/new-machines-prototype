---
name: write-reminders
description: Turn the largest shipped-but-not-paid exceptions into one collection reminder each, from the account manager.
---

Sort `exceptions` by `amount_minor`, highest first, and keep the first `max_messages` of them. For every exception kept, write one draft with these fields:

- `to`: the exception's `customer_email`, unchanged.
- `order_id`: the exception's `order_id`, unchanged.
- `account_manager`: the exception's `account_manager`, or `<company_name> Accounts` when it is null.
- `subject`: `Payment reminder: Invoice <invoice_number> for order <order_id>` (at most 150 characters).
- `body`: plain text, in this order:
  1. A greeting line: `Dear <customer_name>,` (the name before any ` - ` in `customer_name`).
  2. One sentence saying this is a friendly reminder from `<company_name>` about invoice `<invoice_number>` for order `<order_id>`, amounting to `₱<amount>` (centavos converted to pesos with thousands separators and two decimals, for example `₱12,480.00`).
  3. One sentence with the facts: delivered on `<delivered_on>`, payment terms of `<n> days` (or `payment due on delivery` for 0-day terms, the days between `reference_date` and `due_date`), due on `<due_date>`, now `<days past due> days past due` (`days_outstanding` minus the terms).
  4. One sentence asking the customer to disregard the message and send the payment reference if payment has already been made, otherwise to settle at their earliest convenience.
  5. A short closing line of thanks for their continued business.
  6. The sign-off on its own lines: `Maraming salamat po,` then the `account_manager` value above, then `Account Manager, <company_name>`, then the `account_manager_email` when there is one.

Keep each body under 4000 characters. Do not add attachments, links or placeholders such as `[name]`.

Never include email addresses, phone numbers or customer message text in a `note` or `flag`.
