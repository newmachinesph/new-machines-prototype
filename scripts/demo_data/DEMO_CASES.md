# Planted demo cases

All dates below assume `--as-of 2026-10-16` (timestamps are 08:00 UTC, 16:00 Manila, on the day shown).
Every planted id starts with `DEMO-`; the order id is the same in all four systems
(`ecommerce_sales_orders`, `accounting_sales_orders`, `warehouse_served_orders`, `salesapp_sales`), the
customer id is `DEMO-CUST-<case>`, the invoice number `DEMO-INV-<case>`, the commission
`DEMO-COMM-<case>` (exported to Mongo only; the pack does not read commissions), ecommerce payments
`DEMO-PAY-<case>[-PENDING]`. Amounts are PHP. VAT is 12 % inclusive.

Sellers / account managers: **Kristoffer M. Nunez** (`kristoffer.m.nunez@example.com`, `DEMO-USER-SELLER-1`)
and **Yvette D. Tolentino** (`yvette.d.tolentino@example.com`, `DEMO-USER-SELLER-2`).

## Paid but not shipped (`DEMO-PNS-*`)

Ecommerce `paid=true` with a `confirmed` GCash payment, accounting `paid=true`, `balance=0`,
`delivered=false`, a matching accounting customer payment, **no** warehouse served order, salesApp sale
`paid=true`, `delivered=false`. The pack should flag these for the warehouse, oldest first.

| Id | Customer | Seller | Amount | Ordered / paid | Age |
| --- | --- | --- | --- | --- | --- |
| DEMO-PNS-1 | Rafael B. Cabrera - Evergreen Bakeshop | Kristoffer M. Nunez | 18,600.00 | 2026-10-09 | 7 days |
| DEMO-PNS-2 | Blue Horizon Hardware | Yvette D. Tolentino | 7,440.00 | 2026-10-13 | 3 days |
| DEMO-PNS-3 | Vanessa K. Delgado | Kristoffer M. Nunez | 25,920.00 | 2026-10-15 | 1 day |

## Shipped but not paid, past terms (`DEMO-SNP-*`)

Delivered in all systems (ecommerce `status=delivered`, warehouse served order released and delivered,
accounting `delivered=true`, salesApp `delivered=true`), accounting `balance = grandTotal`,
`paid=false`, customer `accountBalance.current = accountBalance.overdue = grandTotal`. Each customer has
an account manager. The pack should draft a collection follow-up for the account manager.

| Id | Customer | Account manager | Amount | Terms | Invoice date | Age | Past terms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEMO-SNP-1 | Gerald S. Evangelista - Highland Food Services | Kristoffer M. Nunez | 40,252.80 | 30 days | 2026-09-01 | 45 days | 15 days |
| DEMO-SNP-2 | Narra Eatery | Yvette D. Tolentino | 12,480.00 | 15 days | 2026-09-15 | 31 days | 16 days |
| DEMO-SNP-3 | Zenaida L. Mercado - Pearl Pastry Shop | Yvette D. Tolentino | 3,150.00 | 0 days (COD) | 2026-10-04 | 12 days | 12 days |

## Payment pending confirmation (`DEMO-PPC-1`)

Delivered 2026-10-06, terms 15 days (not yet past terms), accounting `balance = 15,600.00`, and an
ecommerce payment `DEMO-PAY-PPC-1-PENDING` of 15,600.00 via GCash with `status=pending` created
2026-10-14 (2 days ago). Customer **Bamboo Grocery**, seller Kristoffer M. Nunez. The pack should
**not** chase the customer; it should ask accounting/cashier to confirm the pending payment.

## Disputed, do not chase (`DEMO-DSP-1`)

Customer **Edgardo P. Sarmiento - Riverbend Catering** (`DEMO-CUST-DSP-1`, account manager Yvette D. Tolentino).
Delivered 2026-08-07, 28,800.00 unpaid, terms 30 days, 70 days old, 40 days past terms. The accounting
customer record carries the note:

> Customer disputes invoice — damaged goods, awaiting credit memo

The pack's policy memory references this customer by name; it must be listed as disputed and skipped,
never drafted a collection message.

## Everything else

The other 25 orders in the sandbox fixtures are **synthetic** (`background.py`, fixed seed, nothing derived
from a real business): generator-style customers and three sellers (Gabriel M. Hernandez, Kristoffer O.
Rivera, Rafael C. Dizon), random business-hours moments inside the 30 days before `as_of`, random
quantities of the generic catalogue items (`Sample Item A` to `E`, `plant.PRODUCTS`), ids of the shapes a
business app produces. 19 are paid and delivered (`closed`), 5 are delivered and still inside their
payment terms, and one is deliberately overdue so the pack's fallback to the sales app seller is exercised:

| Id | Customer | Sales app seller | Amount | Terms | Invoice date | Age |
| --- | --- | --- | --- | --- | --- | --- |
| `j5NnyYyrPRE8Fluyy6K-4UV8LlN85P1IVw0H4YL8Lat` (invoice `KKKTSFJUD7APAS`) | Jerome A. Yap | Rafael C. Dizon | 300.00 | 0 days (COD) | 2026-09-23 | 23 days |

The ledger records no account manager and no email for that customer, so the triage names the sales app
seller and recommends `escalate_finance` (no address to write to) rather than a reminder; it stays below
the three planted reminders in amount, so the drafts are unchanged.

The connector's shared two-row samples (`definitions/connectors/sandbox/custom-business-app/`) are two
more synthetic clean orders with short ids (`fixtures.py --connector`). The documents in `out/` (the demo
MongoDB database) are the anonymised export; they are not in the fixtures unless `fixtures.py --clean N`
asks for them. Every planted commission is unclaimed (`commissionClaimed=false`, `commissionClaimId=null`);
`salesapp_commissions` is loaded into the demo database but has no fixture.
