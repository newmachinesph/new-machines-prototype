---
name: write-report
description: Turn the triage, the drafts and what was written into the report and its rows.
---

`sent` is true only when `approval` is not null, its `decision` is `granted`, and the counts you were given show the writes ran (`drafts_created` equals the number of drafts, or there was nothing to draft).

Copy `clean_count` and `totals` from the triage unchanged. `actions` is `{reminders_drafted: drafts_created, finance_notes, warehouse_notes}` from your input.

Build one row per exception in the triage, in the same order:

- `order_id`, `kind`, `customer_name`, `amount_minor`, `currency`, `days_outstanding`: from the exception.
- `note`: the exception's `evidence`.
- `action`, in plain words, from `recommended_action`:
  - `draft_collection_message`: `collection reminder from <account_manager>` (or `from the Accounts desk` when null)
  - `confirm_payment`: `confirm the payment in the ledger`
  - `escalate_finance`: `flag for finance`
  - `nudge_warehouse`: `warehouse note`
  - `none`: `watch: inside the warehouse window`
- `outcome`:
  - `listed` when the action is `none`.
  - `draft_collection_message`: `drafted` when `sent` is true and a draft in `drafts` has the row's `order_id`; otherwise `not_sent`.
  - `confirm_payment` and `escalate_finance`: `noted` only when the row's `order_id` is in `finance_written`; otherwise `not_sent`.
  - `nudge_warehouse`: `noted` only when the row's `order_id` is in `warehouse_written`; otherwise `not_sent`.
  - Decide each row by that membership, never by an aggregate count: a count above 0 says nothing about this order.
  - Held back: when a `not_sent` row's `order_id` is in `drafts_held_back` add ` Held back: the recipient is not on the customer record.` to its `note`; when it is in `notes_held_back` add ` Held back: the order is not in the ledger.`

The summary is two or three sentences: the triage's counts and peso totals, then either `<n> reminders were saved as Gmail drafts, <n> notes posted for finance and <n> for the warehouse.` or `Nothing was sent or posted: the approval was not granted.` (or that nothing was due, when there is no exception).
