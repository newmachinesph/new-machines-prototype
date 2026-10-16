# Planted demo cases

All dates below assume `--as-of 2026-10-16` (timestamps are 08:00 UTC, 16:00 Manila, on the day shown).
Every planted id starts with `DEMO-`; the order id is the same in all four systems
(`ecommerce_sales_orders`, `accounting_sales_orders`, `warehouse_served_orders`, `salesapp_sales`), the
customer id is `DEMO-CUST-<case>`, the invoice number `DEMO-INV-<case>`, the commission
`DEMO-COMM-<case>` (exported to Mongo only; the pack does not read commissions), ecommerce payments
`DEMO-PAY-<case>[-PENDING]`. Amounts are PHP. VAT is 12 % inclusive.

Sellers / account managers: **Ramon C. Villanueva** (`ramon.c.villanueva@example.com`, `DEMO-USER-SELLER-1`)
and **Celeste A. Abad** (`celeste.a.abad@example.com`, `DEMO-USER-SELLER-2`).

## Paid but not shipped (`DEMO-PNS-*`)

Ecommerce `paid=true` with a `confirmed` GCash payment, accounting `paid=true`, `balance=0`,
`delivered=false`, a matching accounting customer payment, **no** warehouse served order, salesApp sale
`paid=true`, `delivered=false`. The pack should flag these for the warehouse, oldest first.

| Id | Customer | Seller | Amount | Ordered / paid | Age |
| --- | --- | --- | --- | --- | --- |
| DEMO-PNS-1 | Jun T. Macaraeg - Starlight Eatery | Ramon C. Villanueva | 18,600.00 | 2026-10-09 | 7 days |
| DEMO-PNS-2 | Golden Harbor Minimart | Celeste A. Abad | 7,440.00 | 2026-10-13 | 3 days |
| DEMO-PNS-3 | Hazel R. Ocampo | Ramon C. Villanueva | 25,920.00 | 2026-10-15 | 1 day |

## Shipped but not paid, past terms (`DEMO-SNP-*`)

Delivered in all systems (ecommerce `status=delivered`, warehouse served order released and delivered,
accounting `delivered=true`, salesApp `delivered=true`), accounting `balance = grandTotal`,
`paid=false`, customer `accountBalance.current = accountBalance.overdue = grandTotal`. Each customer has
an account manager. The pack should draft a collection follow-up for the account manager.

| Id | Customer | Account manager | Amount | Terms | Invoice date | Age | Past terms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEMO-SNP-1 | Teodoro L. Galang - Summit Food Services | Ramon C. Villanueva | 40,252.80 | 30 days | 2026-09-01 | 45 days | 15 days |
| DEMO-SNP-2 | Mabuhay Lechon House | Celeste A. Abad | 12,480.00 | 15 days | 2026-09-15 | 31 days | 16 days |
| DEMO-SNP-3 | Patricia G. Lim - Coral Bakeshop | Celeste A. Abad | 3,150.00 | 0 days (COD) | 2026-10-04 | 12 days | 12 days |

## Payment pending confirmation (`DEMO-PPC-1`)

Delivered 2026-10-06, terms 15 days (not yet past terms), accounting `balance = 15,600.00`, and an
ecommerce payment `DEMO-PAY-PPC-1-PENDING` of 15,600.00 via GCash with `status=pending` created
2026-10-14 (2 days ago). Customer **Sampaguita Snack Bar**, seller Ramon C. Villanueva. The pack should
**not** chase the customer; it should ask accounting/cashier to confirm the pending payment.

## Disputed, do not chase (`DEMO-DSP-1`)

Customer **Marisol Dizon - Bayview Catering** (`DEMO-CUST-DSP-1`, account manager Celeste A. Abad).
Delivered 2026-08-07, 28,800.00 unpaid, terms 30 days, 70 days old, 40 days past terms. The accounting
customer record carries the note:

> Customer disputes invoice — damaged goods, awaiting credit memo

The pack's policy memory references this customer by name; it must be listed as disputed and skipped,
never drafted a collection message.

## Everything else

The remaining documents in `out/` (and the ~25 clean orders in the sandbox fixtures) are real-derived,
anonymised, internally consistent orders that need no action. Every planted commission is unclaimed
(`commissionClaimed=false`, `commissionClaimId=null`); `salesapp_commissions` is loaded into the demo
database but has no fixture.
