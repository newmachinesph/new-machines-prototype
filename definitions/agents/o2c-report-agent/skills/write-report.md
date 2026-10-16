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
  - `confirm_payment`: `confirm the payment in accounting`
  - `escalate_finance`: `flag for finance`
  - `nudge_warehouse`: `warehouse note`
  - `none`: `watch: inside the warehouse window`
- `outcome`:
  - `listed` when the action is `none`.
  - When `sent` is false: `not_sent` for every other action.
  - When `sent` is true: `drafted` for a `draft_collection_message` exception that has a draft with its `order_id`; `not_sent` for one that has none (the cap was reached); `noted` for `confirm_payment`, `escalate_finance` and `nudge_warehouse`.

The summary is two or three sentences: the triage's counts and peso totals, then either `<n> reminders were saved as Gmail drafts, <n> notes posted for finance and <n> for the warehouse.` or `Nothing was sent or posted: the approval was not granted.` (or that nothing was due, when there is no exception).
