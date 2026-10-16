# Demo dataset for the Order-to-Cash Exception Desk pack

Tooling that turns a 120-day window of the four real business systems (ecommerce, accounting,
warehouse, salesApp) into an anonymised demo dataset, plants eight known exceptions on top of it, loads
the result into a fresh MongoDB database and regenerates the pack's sandbox fixtures.

| File | Role |
| --- | --- |
| `export.py` | Reads the sources read-only, trims + anonymises, plants, writes `out/<collection>.json` |
| `anonymize.py` | Pure, deterministic anonymiser and the per-collection field shapes (no database) |
| `plant.py` | Pure builder for the `DEMO-*` exception cases, consistent across all four systems |
| `fixtures.py` | Pure projection of `out/` into `definitions/packs/order-to-cash-exception-desk/sandbox/` |
| `load.py` | Loads `out/*.json` into a new database such as `nm_demo` |
| `DEMO_CASES.md` | Every planted case: id, customer, amounts, dates, expected handling |

Tests: `apps/api/tests/test_demo_data.py` (no database, no pymongo).

## Safety guarantees

- **Sources are read-only.** `export.py` only ever calls `find` with a projection; use a read-only
  database user for the `SRC_*` connection strings anyway.
- **Nothing is written to a source database name.** `load.py` refuses to run when the target database
  is called `ecommerce`, `accounting`, `warehouse` or `salesApp` (any case), when the target URL names
  one of those databases, or when the target URL equals any `SRC_*_URL`.
- **No secrets in logs or in the repo.** Connection strings are read from environment variables and
  never printed. `scripts/demo_data/out/` is gitignored because it is derived from production data;
  only the anonymised sandbox fixtures (small, planted + ~25 representative orders) are committed.
- **Anonymisation is a projection, not a redaction.** Each collection has an explicit shape in
  `anonymize.SHAPES`; a field that is not listed is never fetched from the server (the projection is
  derived from the shape) and never written. Names, emails, phones, addresses and references are
  replaced by values derived from a hash of the real value, so the same real customer becomes the same
  fake customer everywhere and the cross-system joins (`_id`, order references, customer ids) survive.
  Every string that is kept as-is is scrubbed again for anything that still looks like an email, phone
  number or URL.

## Running it

All commands run from the repository root with the API project's interpreter (Python 3.14). `pymongo`
is not a project dependency; `--with pymongo` adds it for the two scripts that talk to MongoDB.

```powershell
# 1. Source connection strings (read-only user). Never commit these.
$env:SRC_ECOMMERCE_URL  = "mongodb+srv://ro-user:...@.../ecommerce"
$env:SRC_ACCOUNTING_URL = "mongodb+srv://ro-user:...@.../accounting"
$env:SRC_WAREHOUSE_URL  = "mongodb+srv://ro-user:...@.../warehouse"
$env:SRC_SALESAPP_URL   = "mongodb+srv://ro-user:...@.../salesApp"

# 2. Export + anonymise + plant, and regenerate the pack fixtures in one go.
uv run --project apps/api --with pymongo python scripts/demo_data/export.py --days 120 --as-of 2026-10-16 --fixtures

# 3. Load into a NEW database (local or a separate cluster), never into a source.
$env:DEMO_MONGO_URL = "mongodb://localhost:27017"
uv run --project apps/api --with pymongo python scripts/demo_data/load.py --db nm_demo --drop

# 4. Regenerate only the sandbox fixtures from an existing out/ (no database needed).
uv run --project apps/api python scripts/demo_data/fixtures.py --as-of 2026-10-16
```

`export.py` options: `--days` (window, default 120), `--as-of YYYY-MM-DD` (end of the window and the
anchor for the planted cases; default today UTC), `--out DIR`, `--limit N` (cap per windowed collection
for a quick trial), `--no-plant`, `--fixtures`. The window is applied to orders, payments, sales,
commissions, served orders and customer payments; the customers and users they reference are fetched
by id/email regardless of date. If the URL names no database, the defaults `ecommerce`, `accounting`,
`warehouse` and `salesApp` are used.

`fixtures.py` writes the seven read-tool files the pack uses (`salesapp_commissions` is exported and
loaded but has no fixture: the pack does not read commissions). It keeps every `DEMO-*` document plus up to `--clean 25` real-derived orders that
exist in all four systems, spread evenly over the 30 days before `--as-of`, with their payments,
customer payments, customers, served orders and sales. When `out/` is missing or holds no planted documents it plants them itself, so the
fixtures can be regenerated without any production data at all.

## Output

`out/<collection>.json`, one JSON array per collection in MongoDB Extended JSON (`{"$date": ...}`),
loaded by `load.py` into a collection of the same name:

`ecommerce_sales_orders`, `ecommerce_payments`, `ecommerce_customers`, `ecommerce_users`,
`accounting_sales_orders`, `accounting_customers`, `accounting_customer_payments`, `accounting_users`,
`warehouse_served_orders`, `salesapp_sales`, `salesapp_commissions`, `salesapp_users`,
`salesapp_customers`.

ObjectId values are exported as plain strings so ids compare the same way in every system. Dates stay
timezone-aware UTC throughout and become ISO-8601 `Z` strings in the fixtures. Amounts stay as PHP
numbers in major units; `currency` is always `"PHP"` in the fixtures.

## What the anonymiser changes

| Real value | Becomes |
| --- | --- |
| Person names (customers, sellers, users, note authors) | Filipino-plausible `First M. Surname`, same name everywhere |
| Business names (`Corp`, `Store`, `Cafe`, `Trading`, ...) | Fake business; `Person - Business` keeps that pattern |
| Emails | `first.m.surname@example.com` derived from the fake name of the person the email belongs to |
| Phones | Fake PH mobile `09XX XXX XXXX` |
| Addresses | Fake street + barangay + city; `zipCode`, `latitude`, `longitude` become `null` |
| TIN, BIR registered name, credit limit, note text | `null` / empty |
| Images, screenshots, documents, logos, signatures, feedback tokens | Dropped |
| Transaction reference numbers / keys | Random 13-digit string from the same seed |
| `myBusiness` | Fictional "Northline Packaging Co." |
| Suppliers | Fake business name only |
| Embedded users (`createdBy.user`, `closedBy`, `userSeller`, `accountManager`, ...) | `{_id, name, email}` |
| Embedded units/products | `{_id, name, measurementUnit, sellingPrice, costPrice, category}` |
| Ids, order references, invoice numbers, amounts, balances, dates, statuses, flags, terms, quantities | Unchanged |
