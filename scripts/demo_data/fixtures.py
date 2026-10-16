"""Project the anonymised + planted data into the pack's sandbox fixtures (pure functions, no database).

    uv run --project apps/api python scripts/demo_data/fixtures.py [--as-of YYYY-MM-DD] [--out DIR]
        [--pack DIR]

Reads `out/*.json` (written by export.py), re-plants the demo cases when none are present, keeps the
planted orders plus up to `--clean` representative real-derived orders from the last 30 days, and writes
one JSON file per read tool of the pack's single `custom-business-app` connector under
`definitions/packs/order-to-cash-exception-desk/sandbox/custom-business-app/` in the connector contract
shape (ISO-8601 UTC strings, amounts in PHP major units). It also removes the stale fixture directories
(`ecommerce/`, `accounting/`, `warehouse/`, `salesapp/` and the old `erp/`) inside that sandbox. The
write tools' fixtures belong to the pack and are never touched; `salesapp_commissions` is exported and
loaded but has no fixture (the pack does not read it).
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import plant  # noqa: E402
from anonymize import as_datetime, from_jsonable, iso_z  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / "out"
PACK_DIR = ROOT / "definitions" / "packs" / "order-to-cash-exception-desk" / "sandbox"
CURRENCY = "PHP"
WINDOW_DAYS = 30
CLEAN_ORDERS = 25

# Published fixture file -> the top-level key its connector tool returns.
FIXTURE_FILES = {
    "custom-business-app/list_store_orders.json": "orders",
    "custom-business-app/list_store_payments.json": "payments",
    "custom-business-app/list_sales_orders.json": "sales_orders",
    "custom-business-app/list_customers.json": "customers",
    "custom-business-app/list_customer_payments.json": "payments",
    "custom-business-app/list_served_orders.json": "served_orders",
    "custom-business-app/list_sales.json": "sales",
}


def _user_name(user: Any) -> str | None:
    return user.get("name") if isinstance(user, dict) else None


def _user_email(user: Any) -> str | None:
    return user.get("email") if isinstance(user, dict) else None


def _note_text(note: Any) -> str:
    if isinstance(note, dict):
        return str(note.get("content") or note.get("text") or "")
    return str(note or "")


def _created_at(doc: dict) -> str | None:
    created = doc.get("createdBy") if isinstance(doc.get("createdBy"), dict) else {}
    return iso_z(created.get("date"))


def ecommerce_order(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "reference": doc.get("salesOrderReference") or doc["_id"],
        "customer_id": doc.get("customerId"),
        "customer_name": doc.get("customerName"),
        "order_date": iso_z(doc.get("orderDate")) or _created_at(doc),
        "status": doc.get("status"),
        "paid": bool(doc.get("paid")),
        "scanned_out": bool(doc.get("scannedOut")),
        "out_for_delivery_at": iso_z(doc.get("outForDeliveryAt")),
        "delivered_at": iso_z(doc.get("deliveredAt")),
        "grand_total": doc.get("grandTotal"),
        "currency": CURRENCY,
        "seller_email": doc.get("userSellerEmail"),
        "payment_method": doc.get("paymentMethod"),
    }


def ecommerce_payment(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "order_id": doc.get("salesOrderId"),
        "customer_id": doc.get("customerId"),
        "amount": doc.get("amount"),
        "currency": CURRENCY,
        "mode_of_payment": doc.get("modeOfPayment"),
        "status": doc.get("status"),
        "payment_date": iso_z(doc.get("paymentDate")),
        "created_at": iso_z(doc.get("createdAt")),
        "reference": doc.get("transactionReferenceNumber"),
    }


def accounting_sales_order(doc: dict) -> dict:
    customer = doc.get("customer") if isinstance(doc.get("customer"), dict) else {}
    manager = customer.get("accountManager")
    return {
        "id": doc["_id"],
        "invoice_number": doc.get("invoiceNumber"),
        "invoice_date": iso_z(doc.get("invoiceDate")),
        "customer_id": customer.get("_id"),
        "customer_name": customer.get("name"),
        "payment_terms_days": customer.get("paymentTerms"),
        "account_manager": _user_name(manager),
        "account_manager_email": _user_email(manager),
        "grand_total": doc.get("grandTotal"),
        "total_payment_received": doc.get("totalPaymentReceived"),
        "balance": doc.get("balance"),
        "currency": CURRENCY,
        "paid": bool(doc.get("paid")),
        "delivered": bool(doc.get("delivered")),
        "delivery_date": iso_z(doc.get("deliveryDate")),
        "is_from_ecommerce": bool(doc.get("isFromEcommerce")),
        "created_at": _created_at(doc),
    }


def accounting_customer(doc: dict) -> dict:
    contact = doc.get("contactDetails") if isinstance(doc.get("contactDetails"), dict) else {}
    balance = doc.get("accountBalance") if isinstance(doc.get("accountBalance"), dict) else {}
    manager = doc.get("accountManager")
    return {
        "id": doc["_id"],
        "name": doc.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "payment_terms_days": doc.get("paymentTerms"),
        "balance_current": balance.get("current"),
        "balance_overdue": balance.get("overdue"),
        "account_manager": _user_name(manager),
        "account_manager_email": _user_email(manager),
        "notes": [text for text in (_note_text(n) for n in doc.get("notesList") or []) if text],
    }


def accounting_customer_payment(doc: dict) -> dict:
    customer = doc.get("customer") if isinstance(doc.get("customer"), dict) else {}
    method = doc.get("paymentMethod")
    return {
        "id": doc["_id"],
        "order_id": doc.get("orderReferenceOfPayment"),
        "customer_id": customer.get("_id"),
        "amount": doc.get("amount"),
        "currency": CURRENCY,
        "method": method.get("method") if isinstance(method, dict) else method,
        "date": _created_at(doc),
    }


def warehouse_served_order(doc: dict) -> dict:
    deliveries = [d for d in doc.get("deliveryList") or [] if isinstance(d, dict)]
    done = [d for d in deliveries if d.get("delivered")]
    delivered_dates = [as_datetime(d.get("deliveryDate")) for d in done]
    latest = max((d for d in delivered_dates if d), default=None)
    return {
        "id": doc["_id"],
        "customer_name": doc.get("customerName"),
        "created_at": iso_z(doc.get("createdDate")),
        "released": bool(doc.get("released")),
        "release_date": iso_z(doc.get("releaseDate")),
        "delivered": bool(doc.get("deliveryDate")) or bool(done),
        "delivered_at": iso_z(doc.get("deliveryDate")) or iso_z(latest),
        "delivery_count": len(deliveries),
        "notes": [text for text in (_note_text(n) for n in doc.get("notesList") or []) if text],
    }


def salesapp_sale(doc: dict) -> dict:
    customer = doc.get("customer") if isinstance(doc.get("customer"), dict) else {}
    return {
        "id": doc["_id"],
        "seller_name": _user_name(doc.get("userSeller")),
        "seller_email": _user_email(doc.get("userSeller")),
        "customer_id": customer.get("_id"),
        "customer_name": customer.get("name"),
        "date": iso_z(doc.get("date")),
        "total": doc.get("totalSale"),
        "currency": CURRENCY,
        "paid": bool(doc.get("paid")),
        "delivered": bool(doc.get("delivered")),
        "closed": bool(doc.get("closed")),
    }


def _order_date(doc: dict) -> datetime | None:
    for key in ("orderDate", "invoiceDate", "date", "createdDate"):
        if doc.get(key) is not None:
            return as_datetime(doc[key])
    created = doc.get("createdBy") if isinstance(doc.get("createdBy"), dict) else {}
    return as_datetime(created.get("date"))


ORDER_SYSTEMS = (
    "ecommerce_sales_orders",
    "accounting_sales_orders",
    "warehouse_served_orders",
    "salesapp_sales",
)


def select_order_ids(data: dict[str, list[dict]], as_of: datetime, clean: int = CLEAN_ORDERS) -> set[str]:
    """The planted order ids plus up to `clean` real-derived orders spread over the last WINDOW_DAYS.

    A sampled order must exist in all four systems, so the fixtures stay consistent across them (a
    cancelled store order that never reached accounting or the warehouse is not a representative order).
    """
    since = as_of - timedelta(days=WINDOW_DAYS)
    present = [{str(d["_id"]) for d in data.get(name, []) if not plant.is_demo(d)} for name in ORDER_SYSTEMS]
    everywhere = set.intersection(*present)
    dated: dict[str, datetime] = {}
    for name in ORDER_SYSTEMS:
        for doc in data.get(name, []):
            oid = str(doc["_id"])
            when = _order_date(doc)
            if oid in everywhere and when and since <= when <= as_of:
                dated.setdefault(oid, when)
    ordered = sorted(dated, key=lambda oid: (dated[oid], oid))
    if len(ordered) > clean:
        step = len(ordered) / clean
        ordered = [ordered[int(i * step)] for i in range(clean)]
    demo = {str(d["_id"]) for n in ORDER_SYSTEMS for d in data.get(n, []) if plant.is_demo(d)}
    return set(ordered) | demo


def build(data: dict[str, list[dict]], as_of: datetime, clean: int = CLEAN_ORDERS) -> dict[str, dict]:
    """Fixture file path -> its JSON body."""
    ids = select_order_ids(data, as_of, clean)
    orders = [d for d in data.get("ecommerce_sales_orders", []) if str(d["_id"]) in ids]
    acct_orders = [d for d in data.get("accounting_sales_orders", []) if str(d["_id"]) in ids]
    sales = [d for d in data.get("salesapp_sales", []) if str(d["_id"]) in ids]
    customer_ids = {str(o.get("customerId")) for o in orders}
    customer_ids |= {
        str(o["customer"].get("_id")) for o in acct_orders if isinstance(o.get("customer"), dict)
    }
    customer_ids |= {str(s["customer"].get("_id")) for s in sales if isinstance(s.get("customer"), dict)}
    customer_payments = [
        d
        for d in data.get("accounting_customer_payments", [])
        if str(d.get("orderReferenceOfPayment")) in ids
    ]
    return {
        "custom-business-app/list_store_orders.json": {"orders": [ecommerce_order(d) for d in orders]},
        "custom-business-app/list_store_payments.json": {
            "payments": [
                ecommerce_payment(d)
                for d in data.get("ecommerce_payments", [])
                if str(d.get("salesOrderId")) in ids
            ]
        },
        "custom-business-app/list_sales_orders.json": {
            "sales_orders": [accounting_sales_order(d) for d in acct_orders]
        },
        "custom-business-app/list_customers.json": {
            "customers": [
                accounting_customer(d)
                for d in data.get("accounting_customers", [])
                if str(d["_id"]) in customer_ids
            ]
        },
        "custom-business-app/list_customer_payments.json": {
            "payments": [accounting_customer_payment(d) for d in customer_payments]
        },
        "custom-business-app/list_served_orders.json": {
            "served_orders": [
                warehouse_served_order(d)
                for d in data.get("warehouse_served_orders", [])
                if str(d["_id"]) in ids
            ]
        },
        "custom-business-app/list_sales.json": {"sales": [salesapp_sale(d) for d in sales]},
    }


def write_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings and one trailing newline, whatever the platform."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip("\n") + "\n")


# Fixture directories from before the four systems were folded into one connector (and its old `erp` name).
STALE_DIRS = ("ecommerce", "accounting", "warehouse", "salesapp", "erp")


def write(fixtures: dict[str, dict], pack_dir: Path = PACK_DIR) -> list[Path]:
    """Write the fixture files under `pack_dir` and drop the stale per-system directories inside it."""
    written = []
    for stale in STALE_DIRS:
        shutil.rmtree(pack_dir / stale, ignore_errors=True)
    for relative, body in fixtures.items():
        path = pack_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_lf(path, json.dumps(body, indent=2, ensure_ascii=False))
        written.append(path)
    return written


def shown(path: Path) -> Path:
    """A path relative to the repo when it is inside it (the usual case), else as given."""
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def read_out(out_dir: Path = OUT_DIR) -> dict[str, list[dict]]:
    """Every `out/<collection>.json` as python documents with aware datetimes."""
    data: dict[str, list[dict]] = {}
    if out_dir.is_dir():
        for path in sorted(out_dir.glob("*.json")):
            data[path.stem] = from_jsonable(json.loads(path.read_text(encoding="utf-8")))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today (UTC)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="directory holding the exported out/*.json")
    parser.add_argument("--pack", type=Path, default=PACK_DIR, help="the pack's sandbox directory")
    parser.add_argument("--clean", type=int, default=CLEAN_ORDERS, help="real-derived orders to keep")
    args = parser.parse_args(argv)
    as_of = plant.as_of_datetime(args.as_of)
    data = read_out(args.out)
    if not any(plant.is_demo(d) for docs in data.values() for d in docs):
        data = plant.apply(data, as_of)
    for path in write(build(data, as_of, args.clean), args.pack):
        print(f"wrote {shown(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
