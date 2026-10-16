"""Plant the demo exceptions on top of the anonymised data (pure functions, no database).

Every planted document has an id that starts with `DEMO-` so it is easy to recognise, is dated relative
to `as_of`, and is written consistently into all four systems (ecommerce, accounting, warehouse,
salesApp) in the trimmed shapes `anonymize.SHAPES` produce. `apply` is idempotent: it first removes any
`DEMO-` document already present. `scripts/demo_data/DEMO_CASES.md` describes each case.
`order_documents` is the shared builder of one order's documents; `background.py` uses it for the
synthetic clean orders around the planted ones.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from anonymize import FICTIONAL_PHONE_PREFIX, MY_BUSINESS, PRODUCT_CATEGORY, email_from_name

DEMO_PREFIX = "DEMO-"
CURRENCY = "PHP"
# The as-of day's business-hours timestamp (16:00 Manila) so planted times look like real activity.
AS_OF_HOUR = 8
VAT_RATE = 1.12
SELLER_COMMISSION_PERCENT = 2.0
COLLECTIONS = (
    "ecommerce_sales_orders",
    "ecommerce_payments",
    "ecommerce_customers",
    "ecommerce_users",
    "accounting_sales_orders",
    "accounting_customers",
    "accounting_customer_payments",
    "accounting_users",
    "warehouse_served_orders",
    "salesapp_sales",
    "salesapp_commissions",
    "salesapp_users",
    "salesapp_customers",
)


def user(id: str, name: str) -> dict[str, str]:
    """An embedded user the way the anonymiser collapses one: `{_id, name, email}`."""
    return {"_id": id, "name": name, "email": email_from_name(name)}


SELLERS = [
    user("DEMO-USER-SELLER-1", "Kristoffer M. Nunez"),
    user("DEMO-USER-SELLER-2", "Yvette D. Tolentino"),
]
WAREHOUSE_USER = user("DEMO-USER-WH-1", "Oscar T. Fajardo")
CASHIER = user("DEMO-USER-CASHIER-1", "Nenita R. Hilario")


def _product(key: str, name: str, selling: float) -> dict[str, Any]:
    return {
        "_id": f"DEMO-UNIT-{key.upper()}",
        "name": name,
        "measurementUnit": "pc",
        "sellingPrice": selling,
        "category": PRODUCT_CATEGORY,
    }


# Generic catalogue items (no real product line, no cost prices); the amounts below come from these prices.
PRODUCTS = {
    "a": _product("a", "Sample Item A", 40.00),
    "b": _product("b", "Sample Item B", 3.00),
    "c": _product("c", "Sample Item C", 6.00),
    "d": _product("d", "Sample Item D", 1.50),
    "e": _product("e", "Sample Item E", 3.20),
}
DISPUTE_NOTE = "Customer disputes invoice — damaged goods, awaiting credit memo"
LEDGER_PAYMENT_DESCRIPTION = "GCash transfer confirmed from the web store"


# One entry per planted order. `age_days` is how old the order/invoice is; `kind` drives the flags.
#   pns: paid, confirmed payment, never shipped          snp: delivered, unpaid, past terms
#   ppc: delivered, unpaid, GCash payment pending
#   dsp: delivered, unpaid, disputed (do not chase)
def _case(
    id: str, kind: str, age_days: int, terms: int, seller: int, customer: str, lines: list[tuple[str, int]]
) -> dict[str, Any]:
    return {
        "id": id,
        "kind": kind,
        "age_days": age_days,
        "terms": terms,
        "seller": seller,
        "customer": customer,
        "lines": lines,
    }


CASES: list[dict[str, Any]] = [
    _case("DEMO-PNS-1", "pns", 7, 15, 0, "Rafael B. Cabrera - Evergreen Bakeshop", [("d", 12400)]),
    _case("DEMO-PNS-2", "pns", 3, 30, 1, "Blue Horizon Hardware", [("b", 2480)]),
    _case("DEMO-PNS-3", "pns", 1, 0, 0, "Vanessa K. Delgado", [("a", 648)]),
    _case(
        "DEMO-SNP-1",
        "snp",
        45,
        30,
        0,
        "Gerald S. Evangelista - Highland Food Services",
        [("a", 990), ("e", 204)],
    ),
    _case("DEMO-SNP-2", "snp", 31, 15, 1, "Narra Eatery", [("c", 2080)]),
    _case("DEMO-SNP-3", "snp", 12, 0, 1, "Zenaida L. Mercado - Pearl Pastry Shop", [("d", 2100)]),
    _case("DEMO-PPC-1", "ppc", 10, 15, 0, "Bamboo Grocery", [("b", 5200)]),
    _case("DEMO-DSP-1", "dsp", 70, 30, 1, "Edgardo P. Sarmiento - Riverbend Catering", [("a", 720)]),
]


def as_of_datetime(value: date | datetime | str | None) -> datetime:
    """`--as-of` as an aware UTC datetime at business hours; a bare date gets AS_OF_HOUR."""
    if value is None:
        value = datetime.now(UTC).date()
    if isinstance(value, str):
        value = (
            date.fromisoformat(value)
            if len(value) == 10
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime(value.year, value.month, value.day, AS_OF_HOUR, tzinfo=UTC)


def is_demo(doc: dict) -> bool:
    return str(doc.get("_id", "")).startswith(DEMO_PREFIX)


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def lines_of(items: list[tuple[str, int]]) -> list[dict]:
    """Order lines (`quantity`, `price`, `unit`) for (product key, quantity) pairs."""
    return [
        {"quantity": qty, "price": PRODUCTS[key]["sellingPrice"], "unit": dict(PRODUCTS[key])}
        for key, qty in items
    ]


def totals_of(lines: list[dict]) -> dict[str, float]:
    grand = money(sum(line["price"] * line["quantity"] for line in lines))
    net = money(grand / VAT_RATE)
    return {"grandTotal": grand, "netOfVat": net, "vatTotal": money(grand - net)}


def empty_data() -> dict[str, list[dict]]:
    return {name: [] for name in COLLECTIONS}


def user_documents(sellers: list[dict], staff: list[dict]) -> dict[str, list[dict]]:
    """The user documents of the three systems that keep users."""
    data = empty_data()
    data["ecommerce_users"] = [dict(u) for u in (*sellers, *staff)]
    data["accounting_users"] = [dict(u) for u in (*sellers, *staff)]
    data["salesapp_users"] = [{**s, "roles": ["seller"], "userType": "seller"} for s in sellers]
    return data


def merge(*parts: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Collections concatenated in order."""
    merged: dict[str, list[dict]] = {}
    for part in parts:
        for name, docs in part.items():
            merged.setdefault(name, []).extend(docs)
    return merged


def order_documents(order: dict[str, Any]) -> dict[str, list[dict]]:
    """One order's documents in all four systems, from an explicit description of it.

    `order` holds: `id`, `invoice_number`, `reference` (the store's order reference), `customer` (`_id`,
    `name`, `email`, `phone`, `address`, `terms`, `manager` (user or None), `notes`, `balances`), `seller`,
    `warehouse_user`, `cashier`, `lines` (from `lines_of`), `paid`, `delivered`, `status`, `payment_method`,
    `times` (`ordered`, `created`, `released`, `delivered`, `closed`; None for steps that never happened),
    `payments` (store payments: `_id`, `amount`, `mode`, `when`, `status`, `reviewer`, `reference`, `key`),
    `ledger_payments` (`_id`, `amount`, `method`, `description`, `when`), `commission` (`_id`) and
    `delivery_id`. Every system sees the same customer, totals and timeline.
    """
    customer, seller, times = order["customer"], order["seller"], order["times"]
    customer_id, name = customer["_id"], customer["name"]
    paid, delivered = order["paid"], order["delivered"]
    totals = totals_of(order["lines"])
    balance = 0.0 if paid else totals["grandTotal"]
    created_by = {"user": dict(seller), "date": times["ordered"]}
    address = {"addressName": customer["address"], "latitude": None, "longitude": None}
    items = [{"quantity": line["quantity"], "unit": line["unit"]} for line in order["lines"]]
    data = empty_data()

    data["ecommerce_sales_orders"].append(
        {
            "_id": order["id"],
            "salesOrderReference": order["reference"],
            "customerId": customer_id,
            "customerName": name,
            "customerContactName": name.split(" - ")[0],
            "customerBusinessName": name.split(" - ")[-1],
            "contactDetails": {
                "phone": customer["phone"],
                "contactPerson": name.split(" - ")[0],
                "email": customer["email"],
            },
            "customerDeliveryAddress": dict(address),
            "itemsOrderList": items,
            "grandTotal": totals["grandTotal"],
            "grandTotalWithFreight": totals["grandTotal"],
            "vatTotal": totals["vatTotal"],
            "netOfVat": totals["netOfVat"],
            "status": order["status"],
            "paid": paid,
            "scannedOut": delivered,
            "orderDate": times["ordered"],
            "outForDeliveryAt": times["released"],
            "deliveredAt": times["delivered"],
            "invoiceNumber": order["invoice_number"],
            "invoiceNumberList": [order["invoice_number"]],
            "invoiceImageList": [],
            "paymentMethod": order["payment_method"],
            "paymentDocuments": [],
            "userSellerEmail": seller["email"],
            "userCreatorEmail": seller["email"],
            "closedBy": dict(seller) if delivered else None,
            "outForDeliveryBy": dict(order["warehouse_user"]) if delivered else None,
            "approvalHold": None,
            "feedbackToken": None,
            "createdBy": created_by,
        }
    )
    for payment in order["payments"]:
        confirmed = payment["status"] == "confirmed"
        reviewer = payment["reviewer"]
        data["ecommerce_payments"].append(
            {
                "_id": payment["_id"],
                "salesOrderId": order["id"],
                "customerId": customer_id,
                "amount": payment["amount"],
                "modeOfPayment": payment["mode"],
                "screenshotUrl": None,
                "transactionReferenceNumber": payment["reference"],
                "transactionReferenceKey": payment["key"],
                "paymentDate": payment["when"] if payment.get("dated", True) else None,
                "status": payment["status"],
                "createdAt": payment["when"],
                "createdByUserId": customer_id,
                "createdByUserEmail": email_from_name(name),
                "reviewedByUserEmail": reviewer["email"] if reviewer else None,
                "reviewedAt": payment["when"] + timedelta(minutes=30) if reviewer else None,
                "rejectionReason": None,
                "accountingPaymentResult": {"paid": True, "balance": 0.0} if confirmed else None,
            }
        )
    data["ecommerce_customers"].append(
        {
            "_id": customer_id,
            "name": name,
            "email": customer["email"],
            "phone": customer["phone"],
            "deliveryAddress": dict(address),
            "paymentTerms": customer["terms"],
            "accountingCustomerId": customer_id,
            "createdBy": created_by,
        }
    )

    accounting_customer = {
        "_id": customer_id,
        "name": name,
        "contactDetails": {
            "address": customer["address"],
            "phone": customer["phone"],
            "email": customer["email"],
            "zipCode": None,
        },
        "bir2303": {"tin": None, "registeredName": None, "photoOfBir2303orCOR": None},
        "paymentTerms": customer["terms"],
        "accountBalance": dict(customer["balances"]),
        "notesList": list(customer["notes"]),
        "accountManager": dict(customer["manager"]) if customer["manager"] else None,
        "creditLimit": None,
        "businessName": name.split(" - ")[-1],
        "createdBy": created_by,
    }
    data["accounting_customers"].append(accounting_customer)
    data["accounting_sales_orders"].append(
        {
            "_id": order["id"],
            "myBusiness": {
                "name": MY_BUSINESS["name"],
                "contactDetails": dict(MY_BUSINESS["contactDetails"]),
            },
            "customer": {
                k: accounting_customer[k]
                for k in (
                    "_id",
                    "name",
                    "contactDetails",
                    "bir2303",
                    "paymentTerms",
                    "accountBalance",
                    "accountManager",
                )
            },
            "itemsOrderList": order["lines"],
            "grandTotal": totals["grandTotal"],
            "netOfVat": totals["netOfVat"],
            "vatTotal": totals["vatTotal"],
            "amountToReceive": totals["grandTotal"],
            "balance": balance,
            "totalPaymentReceived": totals["grandTotal"] if paid else 0.0,
            "paid": paid,
            "delivered": delivered,
            "deliveryDate": times["delivered"],
            "invoiceNumber": order["invoice_number"],
            "invoiceDate": times["ordered"],
            "invoiceImageList": [],
            "isFromEcommerce": True,
            "type": "salesOrder",
            "createdBy": created_by,
        }
    )
    for payment in order["ledger_payments"]:
        data["accounting_customer_payments"].append(
            {
                "_id": payment["_id"],
                "amount": payment["amount"],
                "imageProofsList": [],
                "paymentMethod": {"method": payment["method"], "description": payment["description"]},
                "isPostDatedCheck": False,
                "postDatedCheckDate": None,
                "orderReferenceOfPayment": order["id"],
                "customer": {"_id": customer_id, "name": name},
                "createdBy": {"user": dict(order["cashier"]), "date": payment["when"]},
            }
        )

    if delivered:
        data["warehouse_served_orders"].append(
            {
                "_id": order["id"],
                "customerName": name,
                "createdByUserName": order["warehouse_user"]["name"],
                "createdDate": times["created"],
                "released": True,
                "releaseDate": times["released"],
                "deliveryDate": times["delivered"],
                "itemsOrderList": items,
                "deliveryList": [
                    {
                        "_id": order["delivery_id"],
                        "creationDate": times["released"],
                        "delivered": True,
                        "deliveryDate": times["delivered"],
                    }
                ],
                "notesList": [],
            }
        )

    sale_customer = {
        "_id": customer_id,
        "name": name,
        "email": customer["email"],
        "listOfPhoneNumber": [customer["phone"]] if customer["phone"] else [],
        "accountBalance": dict(customer["balances"]),
    }
    data["salesapp_customers"].append({**sale_customer, "accountManager": dict(seller)})
    data["salesapp_sales"].append(
        {
            "_id": order["id"],
            "userSeller": dict(seller),
            "userCreator": None,
            "customer": sale_customer,
            "date": times["ordered"],
            "paid": paid,
            "delivered": delivered,
            "closed": paid and delivered,
            "closedAt": times["closed"],
            "totalSale": totals["grandTotal"],
            "orderList": order["lines"],
            "involvedUserIds": [seller["_id"]],
        }
    )
    data["salesapp_commissions"].append(
        {
            "_id": order["commission"]["_id"],
            "type": "seller",
            "saleReference": order["id"],
            "user": dict(seller),
            "percentToSeller": SELLER_COMMISSION_PERCENT,
            "percentToCreator": 0.0,
            "commissionsEarned": money(totals["netOfVat"] * SELLER_COMMISSION_PERCENT / 100),
            "commissionClaimed": False,
            "commissionClaimId": None,
            "createdDate": times["ordered"] + timedelta(minutes=5),
            "pointsEarned": 0,
        }
    )
    return data


def _totals(case: dict) -> dict[str, float]:
    return totals_of(lines_of(case["lines"]))


def _customer_id(case: dict) -> str:
    return case["id"].replace("DEMO-", "DEMO-CUST-", 1)


def _invoice_number(case: dict) -> str:
    return case["id"].replace("DEMO-", "DEMO-INV-", 1)


def _timeline(case: dict, as_of: datetime) -> dict[str, datetime | None]:
    """When the order was placed, paid, shipped and delivered; `None` for steps that never happened."""
    ordered = as_of - timedelta(days=case["age_days"])
    delivered = case["kind"] != "pns"
    return {
        "ordered": ordered,
        "paid": ordered + timedelta(hours=1) if case["kind"] == "pns" else None,
        "released": ordered + timedelta(hours=3) if delivered else None,
        "delivered": ordered + timedelta(hours=7) if delivered else None,
        "pending_payment": as_of - timedelta(days=2) if case["kind"] == "ppc" else None,
    }


def _flags(case: dict) -> dict[str, bool]:
    kind = case["kind"]
    return {"paid": kind == "pns", "delivered": kind != "pns"}


def _balances(case: dict, as_of: datetime) -> dict[str, float]:
    """The customer's open balance and how much of it is past its payment terms."""
    total = _totals(case)["grandTotal"]
    if _flags(case)["paid"]:
        return {"current": 0.0, "overdue": 0.0}
    overdue = total if case["age_days"] > case["terms"] else 0.0
    return {"current": total, "overdue": overdue}


def _store_payment(case: dict, amount: float, when: datetime, status: str, reviewer: dict | None) -> dict:
    suffix = "" if status == "confirmed" else "-PENDING"
    index = CASES.index(case)
    return {
        "_id": case["id"].replace("DEMO-", "DEMO-PAY-", 1) + suffix,
        "amount": amount,
        "mode": "GCash",
        "when": when,
        "status": status,
        "reviewer": reviewer,
        "reference": f"{7000000000000 + index * 1111:013d}",
        "key": f"{8000000000000 + index * 2222:013d}",
    }


def _order(case: dict, as_of: datetime) -> dict[str, Any]:
    """The explicit description `order_documents` builds a planted case from."""
    index = CASES.index(case)
    seller = SELLERS[case["seller"]]
    times = _timeline(case, as_of)
    flags = _flags(case)
    total = _totals(case)["grandTotal"]
    payments = []
    if times["paid"]:
        payments.append(_store_payment(case, total, times["paid"], "confirmed", seller))
    if times["pending_payment"]:
        payments.append(_store_payment(case, total, times["pending_payment"], "pending", None))
    notes = (
        [{"content": DISPUTE_NOTE, "createdDate": as_of - timedelta(days=5), "userName": CASHIER["name"]}]
        if case["kind"] == "dsp"
        else []
    )
    return {
        "id": case["id"],
        "reference": case["id"],
        "invoice_number": _invoice_number(case),
        "customer": {
            "_id": _customer_id(case),
            "name": case["customer"],
            "email": email_from_name(case["customer"]),
            "phone": f"{FICTIONAL_PHONE_PREFIX}{2200 + 7 * index:04d}",
            "address": f"{12 + index} Sample Street, Example Quarter, Sampletown",
            "terms": case["terms"],
            "manager": seller,
            "notes": notes,
            "balances": _balances(case, as_of),
        },
        "seller": seller,
        "warehouse_user": WAREHOUSE_USER,
        "cashier": CASHIER,
        "lines": lines_of(case["lines"]),
        "paid": flags["paid"],
        "delivered": flags["delivered"],
        "status": "delivered" if flags["delivered"] else "pending",
        "payment_method": "GCash" if case["kind"] in ("pns", "ppc") else "Bank Transfer",
        "times": {
            "ordered": times["ordered"],
            "created": times["ordered"] + timedelta(hours=2),
            "released": times["released"],
            "delivered": times["delivered"],
            "closed": None,
        },
        "payments": payments,
        "ledger_payments": [
            {
                "_id": case["id"].replace("DEMO-", "DEMO-CPAY-", 1),
                "amount": total,
                "method": "GCash",
                "description": LEDGER_PAYMENT_DESCRIPTION,
                "when": times["paid"],
            }
        ]
        if flags["paid"]
        else [],
        "commission": {"_id": case["id"].replace("DEMO-", "DEMO-COMM-", 1)},
        "delivery_id": case["id"].replace("DEMO-", "DEMO-DLV-", 1),
    }


def build(as_of: datetime) -> dict[str, list[dict]]:
    """Every planted document, grouped by out/ collection name."""
    orders = (order_documents(_order(case, as_of)) for case in CASES)
    return merge(user_documents(SELLERS, [CASHIER]), *orders)


def apply(data: dict[str, list[dict]], as_of: datetime) -> dict[str, list[dict]]:
    """Return `data` with every existing `DEMO-` document removed and the planted cases added."""
    planted = build(as_of)
    merged: dict[str, list[dict]] = {}
    for name in set(data) | set(planted):
        merged[name] = [doc for doc in data.get(name, []) if not is_demo(doc)] + planted.get(name, [])
    return merged


def summary(as_of: datetime) -> list[dict[str, Any]]:
    """One row per case for DEMO_CASES.md and the tests."""
    rows = []
    for case in CASES:
        totals = _totals(case)
        times = _timeline(case, as_of)
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "customer": case["customer"],
                "customer_id": _customer_id(case),
                "seller": SELLERS[case["seller"]]["name"],
                "grand_total": totals["grandTotal"],
                "terms": case["terms"],
                "age_days": case["age_days"],
                "days_past_terms": max(0, case["age_days"] - case["terms"]),
                "ordered": times["ordered"],
                "balances": _balances(case, as_of),
            }
        )
    return rows
