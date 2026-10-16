# Demo dataset for the Order-to-Cash Exception Desk pack

Tooling that turns a 120-day window of the four real business systems (ecommerce, accounting,
warehouse, salesApp) into an anonymised demo dataset, plants eight known exceptions on top of it and loads
the result into a fresh MongoDB database. The pack's committed sandbox fixtures are generated **without**
any of that data: the planted cases plus synthetic background orders (`background.py`), so nothing in the
repository derives from the real business.

| File | Role |
| --- | --- |
| `export.py` | Reads the sources read-only, trims + anonymises, plants, writes `out/<collection>.json` |
| `anonymize.py` | Pure, keyed (`DEMO_ANON_KEY`) anonymiser and the per-collection field shapes (no database) |
| `check_leaks.py` | Flags real-looking emails, URLs, phones, TINs and `forbid.txt` entries in JSON folders |
| `plant.py` | Pure builder for the `DEMO-*` exception cases and the shared one-order document builder |
| `background.py` | Pure, seeded builder of synthetic clean orders for the fixtures (no key, no database) |
| `fixtures.py` | Pure projection of planted + synthetic (+ optionally `out/`) documents into the two sandbox folders |
| `load.py` | Loads `out/*.json` into a new database such as `nm_demo` |
| `DEMO_CASES.md` | Every planted case: id, customer, amounts, dates, expected handling; the synthetic background |

Tests: `apps/api/tests/test_demo_data.py` (no database, no pymongo) and
`apps/api/tests/test_demo_fixtures_clean.py` (the committed sandbox folders hold only fictional data).

## Safety guarantees

- **Sources are read-only.** `export.py` only ever calls `find` with a projection; use a read-only
  database user for the `SRC_*` connection strings anyway.
- **Nothing is written to a source database name.** `load.py` refuses to run when the target database
  is called `ecommerce`, `accounting`, `warehouse` or `salesApp` (any case), when the target URL names
  one of those databases, or when the target URL equals, or is on the same host as, any `SRC_*_URL`.
  A MongoDB error in `export.py` or `load.py` prints one generic line, never a host name.
- **No secrets in logs or in the repo.** Connection strings and `DEMO_ANON_KEY` are read from
  environment variables and never printed. `scripts/demo_data/out/` is gitignored because it is derived
  from production data; the committed sandbox fixtures hold only the planted cases and synthetic orders.
- **Anonymisation is a projection, not a redaction.** Each collection has an explicit shape in
  `anonymize.SHAPES`; a field that is not listed is never fetched from the server (the projection is
  derived from the shape) and never written. Names, emails, phones, addresses, ids, invoice numbers and
  references are replaced by values derived with HMAC-SHA256 under the secret `DEMO_ANON_KEY`, so the
  same real customer becomes the same fake customer everywhere and the cross-system joins (`_id`,
  order references, customer ids) survive, while nobody without the key can rebuild the mapping or
  brute-force a phone number. Every timestamp moves forward by one secret number of days (30 to 150,
  derived from the same key; the export reads a window that ended that long ago) and then back by an
  offset of its own order chain (up to 14 whole days plus a time of day), so no real date or time
  survives and no single delta links old and new dates; the events of one order keep their sequence.
  Every amount of a chain is scaled by one chain-specific factor (0.8 to 1.2, rounded to centavos), unit
  cost prices are never exported, and free text is replaced by fixed values.
- **The key.** Export refuses to run without `DEMO_ANON_KEY` (16+ characters, e.g.
  `python -c "import secrets; print(secrets.token_hex(32))"`). Keep it in a password manager, never in
  the repo, a `.env` file that is committed, a log or a chat. Reuse the same key for a re-export if you
  want the same fake names and ids as the last one; use a new key to cut every link to the old export.
  Losing it costs nothing but that continuity. Do not store an old-to-new mapping anywhere.
- **Leak check.** `check_leaks.py` runs at the end of `export.py` and flags emails outside `example.com`,
  URLs of any scheme (`http(s)://`, `gs://`, `ftp://`, `www.`), phones outside `+63 900 000 XXXX`,
  TIN-like numbers and every entry of `scripts/demo_data/forbid.txt` (untracked, gitignored: one real
  customer name, street or company per line, `#` for comments). Fill `forbid.txt` before an export; a
  forbidden entry is reported by number, never echoed. Run it on the committed sandbox folders too.
  Every string that is kept as-is is scrubbed again for anything that still looks like an email, phone
  number or URL.

## Running it

Set the key first (see "The key" above), for example `$env:DEMO_ANON_KEY = "<your secret>"`.

All commands run from the repository root with the API project's interpreter (Python 3.14). `pymongo`
is not a project dependency; `--with pymongo` adds it for the two scripts that talk to MongoDB.

```powershell
# 1. Source connection strings (read-only user). Never commit these.
$env:SRC_ECOMMERCE_URL  = "mongodb+srv://ro-user:...@.../ecommerce"
$env:SRC_ACCOUNTING_URL = "mongodb+srv://ro-user:...@.../accounting"
$env:SRC_WAREHOUSE_URL  = "mongodb+srv://ro-user:...@.../warehouse"
$env:SRC_SALESAPP_URL   = "mongodb+srv://ro-user:...@.../salesApp"

# 2. Export + anonymise + plant (and, with --fixtures, regenerate the pack fixtures too).
uv run --project apps/api --with pymongo python scripts/demo_data/export.py --days 120 --as-of 2026-10-16

# 3. Load into a NEW database (local or a separate cluster), never into a source.
$env:DEMO_MONGO_URL = "mongodb://localhost:27017"
uv run --project apps/api --with pymongo python scripts/demo_data/load.py --db nm_demo --drop

# 4. Regenerate the committed sandbox fixtures (no database, no key, no out/ needed): the planted cases,
#    25 synthetic background orders and the connector's two-row samples.
uv run --project apps/api python scripts/demo_data/fixtures.py --as-of 2026-10-16 --connector
```

`export.py` options: `--days` (window, default 120), `--as-of YYYY-MM-DD` (the date the demo clock
reads at the end of the exported window and the anchor for the planted cases; default today. The source
window read ends the secret shift *before* it, and the anonymiser moves every chain forward by the shift
less its own offset, so the exported dates land in `[as-of - days - 15, as-of]` and `as-of` itself tells
nothing about the shift), `--out DIR`, `--limit N` (cap per windowed collection for a quick trial),
`--no-plant`, `--fixtures` (with `--clean N` to put N anonymised orders into the fixtures beside the
synthetic ones; default none). The window is applied to orders, payments, sales, commissions, served
orders and customer payments; the customers and users they reference are fetched by id/email regardless
of date. If the URL names no database, the defaults `ecommerce`, `accounting`, `warehouse` and `salesApp`
are used.

`fixtures.py` writes the seven read-tool files of the pack's single `custom-business-app` connector
(`list_store_orders`, `list_store_payments`, `list_sales_orders`, `list_customers`,
`list_customer_payments`, `list_served_orders`, `list_sales`) and deletes the stale directories
`ecommerce/`, `accounting/`, `warehouse/`, `salesapp/` and the old `erp/` inside that sandbox
(`salesapp_commissions` is exported and loaded but has no fixture: the pack does not read commissions).
It always plants the `DEMO-*` cases and adds `--background 25` synthetic orders (`background.py`: fixed
seed, generator names, random business-hours moments in the 30 days before `--as-of`, generic catalogue
items, one deliberately overdue order; see `DEMO_CASES.md`). Only with `--clean N` does it also keep up
to N anonymised orders from `out/` that exist in all four systems, spread over the same 30 days, with
their payments, customers, served orders and sales. `--connector` rewrites the connector's shared two-row
samples under `definitions/connectors/sandbox/custom-business-app/` from two synthetic orders with short
ids. Run `check_leaks.py` and `apps/api/tests/test_demo_fixtures_clean.py` on the result.

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
| Person names (customers, sellers, users, note authors) | Filipino-plausible `First M. Surname` from the generator's lists, same name everywhere under one key |
| Business names (`Corp`, `Store`, `Cafe`, `Trading`, ...) | Fake business; `Person - Business` keeps that pattern |
| Emails | `first.m.surname@example.com` derived from the fake name of the person the email belongs to |
| Phones | `+63 900 000 XXXX`, a range assigned to no carrier |
| Addresses | Fake street + barangay + city; `zipCode`, `latitude`, `longitude` become `null` |
| TIN, BIR registered name, credit limit, note text | `null` / empty |
| Images, screenshots, documents, logos, signatures, feedback tokens | Dropped |
| Transaction reference numbers / keys | Random 13-digit string from the same seed |
| `myBusiness` | Fictional "Kalumpang Demo Supply Co.", an invented address and a `+63 900 000` phone |
| Suppliers | Fake business name only |
| Embedded users (`createdBy.user`, `closedBy`, `userSeller`, `accountManager`, ...) | `{_id, name, email}` |
| Embedded units/products | `{_id, name, measurementUnit, sellingPrice, category}`; the selling price is scaled with the chain, `costPrice` is dropped |
| Ids (`_id`, customer ids, auth uids, 43-character digests), order references, invoice numbers | A keyed stand-in of the same length and character set, identical in every collection so joins hold |
| Timestamps (BSON dates, ISO strings or epoch numbers under a date key) | Forward by the secret shift, back by the order chain's own whole days and time of day; one order's events keep their sequence |
| Amounts, balances, prices, commissions | Scaled by the order chain's factor (0.8 to 1.2), rounded to centavos; a customer's balance by the customer's own factor |
| Store `paymentMethod` | The method name only (string, or `{method, description: null}` when the source embeds a document) |
| Free text (`approvalHold.reason`, `rejectionReason`, `paymentMethod.description`, product names and categories) | Fixed values (`Held for review`, `Rejected by reviewer`, `null`, `Product <id suffix>`, `General`) |
| Statuses, flags, terms, quantities | Unchanged |
