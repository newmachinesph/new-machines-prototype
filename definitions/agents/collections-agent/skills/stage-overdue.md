---
name: stage-overdue
description: Decide which invoices are overdue, how late each is, and the reminder stage.
---

For each invoice in `invoices` (the list is under `data`):

1. Skip it unless `status` is `open`.
2. The due date is the calendar date (UTC) of `due_date`, a Unix timestamp in seconds.
3. Days overdue = `as_of` minus the due date, in whole days. Skip the invoice unless it is at least 1.
4. The stage follows from the days overdue:
   - 1 to 14 days: `gentle`
   - 15 to 44 days: `firm`
   - 45 days or more: `final` (a final notice)

For every overdue invoice, in the order the invoices were given, write:

**A message** `{to, about, facts, ref}`:

- `to`: the invoice's `customer_email`.
- `ref`: the invoice number, the same `ref` as the invoice's review item.
- `about`: `Invoice <number> is <days> days overdue`.
- `facts`, in this order:
  1. `Invoice number: <number>`
  2. `Amount due: <amount> <CURRENCY>`, with `amount_due` converted to major units with thousands separators and two decimals, for example `1,250.00 USD`.
  3. `Due date: <YYYY-MM-DD>`
  4. `Stage: <stage> (<days> days overdue)`, writing `final notice` for the final stage.

**A review item** `{ref, date, amount_minor, currency, flag, note}`:

- `ref`: the invoice number. `date`: the due date. `amount_minor`: `amount_due`. `currency`: upper case.
- `flag`: `Overdue <days> days (<stage>)`, for example `Overdue 21 days (firm)`.
- `note`: one sentence giving the reason for the stage, for example `21 days past due, which is in the 15 to 44 day band, so the reminder is firm.`
- Never include email addresses, phone numbers or customer message text in a `note` or `flag`.

The summary is one or two sentences: invoices checked, how many are overdue, and how many are gentle, firm and final.
