"""Export a trimmed, anonymised window of the four source databases to `out/<collection>.json`.

    uv run --project apps/api --with pymongo python scripts/demo_data/export.py [--days 120] [--as-of DATE]
        [--fixtures]

Reads READ-ONLY (only `find` with projections) from the clusters named by `SRC_ECOMMERCE_URL`,
`SRC_ACCOUNTING_URL`, `SRC_WAREHOUSE_URL` and `SRC_SALESAPP_URL` (never printed). Takes the orders,
payments, sales, commissions and served orders created in the last `--days` days plus every customer and
user they reference, keeps only the fields `anonymize.SHAPES` list (so the giant embedded unit documents
never leave the server), anonymises them deterministically, plants the demo exceptions (unless
`--no-plant`) and writes MongoDB Extended JSON arrays, then runs `check_leaks.py` over them and deletes the
output if anything real-looking survived. `--fixtures` also regenerates the pack's sandbox fixtures from
the result. Nothing is ever written to a source database.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_leaks  # noqa: E402
import fixtures  # noqa: E402
import plant  # noqa: E402
from anonymize import SHAPES, Anonymizer, jsonable, projection, transform_all  # noqa: E402

OUT_DIR = fixtures.OUT_DIR
# (env var, default database name when the URL names none)
SOURCES = {
    "ecommerce": ("SRC_ECOMMERCE_URL", "ecommerce"),
    "accounting": ("SRC_ACCOUNTING_URL", "accounting"),
    "warehouse": ("SRC_WAREHOUSE_URL", "warehouse"),
    "salesapp": ("SRC_SALESAPP_URL", "salesApp"),
}
# out/ collection name -> (source system, source collection)
COLLECTIONS = {
    "ecommerce_sales_orders": ("ecommerce", "SalesOrders"),
    "ecommerce_payments": ("ecommerce", "Payments"),
    "ecommerce_customers": ("ecommerce", "Customers"),
    "ecommerce_users": ("ecommerce", "Users"),
    "accounting_sales_orders": ("accounting", "SalesOrders"),
    "accounting_customers": ("accounting", "Customers"),
    "accounting_customer_payments": ("accounting", "CustomerPayments"),
    "accounting_users": ("accounting", "Users"),
    "warehouse_served_orders": ("warehouse", "ServedOrders"),
    "salesapp_sales": ("salesapp", "Sales"),
    "salesapp_commissions": ("salesapp", "Commissions"),
    "salesapp_users": ("salesapp", "Users"),
    "salesapp_customers": ("salesapp", "Customers"),
}
USER_ID_KEYS = ("createdByUserId", "involvedUserIds")


def fail(message: str) -> int:
    print(f"EXPORT FAILED: {message}", file=sys.stderr)
    return 1


def plain(value: Any) -> Any:
    """BSON scalars (ObjectId, Decimal128, Int64) as plain python so the pure modules never see bson."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    kind = type(value).__name__
    if kind == "ObjectId":
        return str(value)
    if kind == "Decimal128":
        return float(value.to_decimal())
    if kind == "Int64":
        return int(value)
    return value


def id_variants(values: set[str]) -> list[Any]:
    """Each id as a string and, when it is a 24-hex string, also as an ObjectId (collections differ)."""
    from bson import ObjectId

    out: list[Any] = []
    for value in values:
        out.append(value)
        if ObjectId.is_valid(value):
            out.append(ObjectId(value))
    return out


def collect_refs(docs: list[dict]) -> tuple[set[str], set[str], set[str]]:
    """Order ids, customer ids and user ids/emails referenced by a batch of raw documents."""
    orders: set[str] = set()
    customers: set[str] = set()
    users: set[str] = set()

    def walk(value: Any, key: str | None = None) -> None:
        if isinstance(value, dict):
            if key in ("customer",) and value.get("_id") is not None:
                customers.add(str(value["_id"]))
            if "email" in value and value.get("_id") is not None:
                users.add(str(value["_id"]))
            if isinstance(value.get("email"), str):
                users.add(value["email"].strip().lower())
            for k, v in value.items():
                if k in ("customerId",) and v is not None:
                    customers.add(str(v))
                elif k in ("salesOrderId", "saleReference", "orderReferenceOfPayment") and v is not None:
                    orders.add(str(v))
                elif k in (
                    "userSellerEmail",
                    "userCreatorEmail",
                    "createdByUserEmail",
                    "reviewedByUserEmail",
                ):
                    if isinstance(v, str) and v.strip():
                        users.add(v.strip().lower())
                elif k in USER_ID_KEYS:
                    for item in v if isinstance(v, list) else [v]:
                        if item is not None:
                            users.add(str(item))
                else:
                    walk(v, k)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)

    for doc in docs:
        if doc.get("_id") is not None:
            orders.add(str(doc["_id"]))
        walk(doc)
    return orders, customers, users


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--days", type=int, default=120, help="window length in days (default 120)")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD end of the window; defaults to today (UTC)")
    parser.add_argument(
        "--out", type=Path, default=OUT_DIR, help="output directory (default scripts/demo_data/out)"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="cap documents per windowed collection (0 = no cap)"
    )
    parser.add_argument("--no-plant", action="store_true", help="skip planting the DEMO- exception cases")
    parser.add_argument("--fixtures", action="store_true", help="also regenerate the pack sandbox fixtures")
    args = parser.parse_args(argv)

    missing = [var for var, _ in SOURCES.values() if not os.environ.get(var, "").strip()]
    if missing:
        return fail(f"set {', '.join(missing)} to the source MongoDB connection strings (read-only user)")

    from pymongo import MongoClient

    as_of = plant.as_of_datetime(args.as_of)
    since = as_of - timedelta(days=args.days)
    clients = {
        name: MongoClient(os.environ[var].strip(), serverSelectionTimeoutMS=20000)
        for name, (var, _) in SOURCES.items()
    }
    dbs = {
        name: clients[name].get_default_database(default=default) for name, (_, default) in SOURCES.items()
    }

    def fetch(collection: str, query: dict) -> list[dict]:
        system, source = COLLECTIONS[collection]
        cursor = dbs[system][source].find(query, projection(collection))
        if args.limit:
            cursor = cursor.limit(args.limit)
        docs = [plain(doc) for doc in cursor]
        print(f"{system}.{source}: {len(docs)} documents")
        return docs

    raw: dict[str, list[dict]] = {}
    raw["ecommerce_sales_orders"] = fetch(
        "ecommerce_sales_orders",
        {"$or": [{"orderDate": {"$gte": since}}, {"createdBy.date": {"$gte": since}}]},
    )
    order_ids, customer_ids, user_refs = collect_refs(raw["ecommerce_sales_orders"])
    ids = id_variants(order_ids)
    raw["ecommerce_payments"] = fetch(
        "ecommerce_payments",
        {
            "$or": [
                {"createdAt": {"$gte": since}},
                {"paymentDate": {"$gte": since}},
                {"salesOrderId": {"$in": ids}},
            ]
        },
    )
    raw["accounting_sales_orders"] = fetch(
        "accounting_sales_orders",
        {
            "$or": [
                {"invoiceDate": {"$gte": since}},
                {"createdBy.date": {"$gte": since}},
                {"_id": {"$in": ids}},
            ]
        },
    )
    raw["warehouse_served_orders"] = fetch(
        "warehouse_served_orders", {"$or": [{"createdDate": {"$gte": since}}, {"_id": {"$in": ids}}]}
    )
    raw["salesapp_sales"] = fetch(
        "salesapp_sales", {"$or": [{"date": {"$gte": since}}, {"_id": {"$in": ids}}]}
    )
    raw["salesapp_commissions"] = fetch(
        "salesapp_commissions", {"$or": [{"createdDate": {"$gte": since}}, {"saleReference": {"$in": ids}}]}
    )
    raw["accounting_customer_payments"] = fetch(
        "accounting_customer_payments",
        {"$or": [{"createdBy.date": {"$gte": since}}, {"orderReferenceOfPayment": {"$in": ids}}]},
    )

    for name in list(raw):
        _, more_customers, more_users = collect_refs(raw[name])
        customer_ids |= more_customers
        user_refs |= more_users
    customers = id_variants(customer_ids)
    users = id_variants({u for u in user_refs if "@" not in u})
    emails = sorted(u for u in user_refs if "@" in u)
    for name in ("ecommerce_customers", "accounting_customers", "salesapp_customers"):
        raw[name] = fetch(name, {"_id": {"$in": customers}})
    for name in ("ecommerce_users", "accounting_users", "salesapp_users"):
        raw[name] = fetch(name, {"$or": [{"_id": {"$in": users}}, {"email": {"$in": emails}}]})
    for client in clients.values():
        client.close()

    data = transform_all(Anonymizer(), {name: raw.get(name, []) for name in SHAPES})
    if not args.no_plant:
        data = plant.apply(data, as_of)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, docs in data.items():
        path = args.out / f"{name}.json"
        fixtures.write_lf(path, json.dumps(jsonable(docs), indent=1, ensure_ascii=False))
        print(f"wrote {path} ({len(docs)} documents)")
    leaks = check_leaks.scan_dir(args.out)
    if leaks:
        check_leaks.report(leaks)
        shutil.rmtree(args.out, ignore_errors=True)
        return fail(f"{len(leaks)} leak(s) found in the export; {args.out} was deleted")
    print(f"leak check passed for {args.out}")
    if args.fixtures:
        for path in fixtures.write(fixtures.build(data, as_of)):
            print(f"wrote {fixtures.shown(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
