---
name: check-expenses
description: Categorise one week of expenses, flag the unusual ones and prepare the summary.
---

`sheet` is a spreadsheet read: `valueRanges[0].values` is a list of rows. The first row is the header: Date, Description, Amount, Paid by, Receipt. Row numbers start at 1 for the header, so the first expense is row 2.

1. The week is `week_start` and the six days after it; `week_end` is the last of them. Keep only rows whose Date (YYYY-MM-DD) is in the week.
2. Amount is in dollars, such as `48.50` or `$1,234.50`; write it as cents. Receipt is `yes` or `no`.
3. Category, from the description: Travel (flight, train, taxi, hotel, parking, mileage), Meals (lunch, dinner, breakfast, coffee, meal), Software (subscription, software, licence, plan, app), Office (paper, toner, printer, desk, chair, stationery, supplies), else Other.
4. Flag at most one reason per expense, checked in this order, using the expense policy in `rules`:
   - over 500.00 USD: flag `Over the $500 limit`;
   - 25.00 USD or more with no receipt: flag `No receipt for $25 or more`;
   - same description (ignoring case) and same amount as an earlier expense within 7 days: flag `Possible duplicate of row N`, where N is the earlier row.
   Each flag is one review item: `ref` is `Row N`, with the date, the amount in cents, `USD`, the flag and a one-sentence note on the rule it breaks.
5. `categories` lists Travel, Meals, Software, Office, Other in that order, only those with expenses.
6. `summary_rows`: one row per category, `[week_start, category, count, amount]`, then `[week_start, "Total", count, amount]`. Counts and amounts are text, amounts in dollars with two decimals and no currency, such as `723.50`.
7. `email_facts`, in order. Write `1 item` for one and `<count> items` for any other count:
   - `Expenses from <week_start> to <week_end>: <count> items, <total> USD in total.` (`... 1 item, ...` for one expense)
   - one fact per category: `<Category>: <count> items, <amount> USD.` (`Travel: 1 item, 48.50 USD.` for one)
   - when one expense is flagged: `1 expense is flagged for a check: Row 6 (No receipt for $25 or more).`; when more are: `<n> expenses are flagged for a check: Row 6 (No receipt for $25 or more); ...`; otherwise `No expense needed a check.`
8. With no expenses in the week, every list is empty.

Never include email addresses, phone numbers or customer message text in a `note` or `flag`.
