"""Plant the demo exceptions on top of the anonymised data (pure functions, no database).

Every planted document has an id that starts with `DEMO-` so it is easy to recognise, is dated relative
to `as_of`, and is written consistently into all four systems (ecommerce, accounting, warehouse,
salesApp) in the trimmed shapes `anonymize.SHAPES` produce. `apply` is idempotent: it first removes any
`DEMO-` document already present. `scripts/demo_data/DEMO_CASES.md` describes each case.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from anonymize import MY_BUSINESS, email_from_name

DEMO_PREFIX = "DEMO-"
CURRENCY = "PHP"
# The as-of day's business-hours timestamp (16:00 Manila) so planted times look like real activity.
AS_OF_HOUR = 8

SELLERS = [
    {
        "_id": "DEMO-USER-SELLER-1",
        "name": "Ramon C. Villanueva",
        "email": email_from_name("Ramon C. Villanueva"),
    },
    {"_id": "DEMO-USER-SELLER-2", "name": "Celeste A. Abad", "email": email_from_name("Celeste A. Abad")},
]
WAREHOUSE_USER = "Dindo P. Suico"
CASHIER = {
    "_id": "DEMO-USER-CASHIER-1",
    "name": "Lorna B. Pascual",
    "email": email_from_name("Lorna B. Pascual"),
}


def _product(key: str, name: str, selling: float, cost: float, category: str) -> dict[str, Any]:
    return {
        "_id": f"DEMO-UNIT-{key.upper()}",
        "name": name,
        "measurementUnit": "pc",
        "sellingPrice": selling,
        "costPrice": cost,
        "category": category,
    }


PRODUCTS = {
    "box": _product("box", "Corrugated Box 12x12x12", 38.40, 29.50, "Boxes"),
    "cup": _product("cup", "Paper Cup 12oz", 2.40, 1.70, "Cups"),
    "tray": _product("tray", "Food Tray #2", 5.20, 3.90, "Trays"),
    "kraft": _product("kraft", "Kraft Paper Bag #6", 3.15, 2.30, "Bags"),
    "pp": _product("pp", "PP Plastic Bag 8x12", 1.55, 1.05, "Bags"),
}
DISPUTE_NOTE = "Customer disputes invoice — damaged goods, awaiting credit memo"


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
    _case("DEMO-PNS-1", "pns", 7, 15, 0, "Jun T. Macaraeg - Starlight Eatery", [("pp", 12000)]),
    _case("DEMO-PNS-2", "pns", 3, 30, 1, "Golden Harbor Minimart", [("cup", 3100)]),
    _case("DEMO-PNS-3", "pns", 1, 0, 0, "Hazel R. Ocampo", [("box", 675)]),
    _case(
        "DEMO-SNP-1",
        "snp",
        45,
        30,
        0,
        "Teodoro L. Galang - Summit Food Services",
        [("box", 1000), ("cup", 772)],
    ),
    _case("DEMO-SNP-2", "snp", 31, 15, 1, "Mabuhay Lechon House", [("tray", 2400)]),
    _case("DEMO-SNP-3", "snp", 12, 0, 1, "Patricia G. Lim - Coral Bakeshop", [("kraft", 1000)]),
    _case("DEMO-PPC-1", "ppc", 10, 15, 0, "Sampaguita Snack Bar", [("cup", 6500)]),
    _case("DEMO-DSP-1", "dsp", 70, 30, 1, "Marisol Dizon - Bayview Catering", [("box", 750)]),
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


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _lines(case: dict) -> list[dict]:
    return [
        {"quantity": qty, "price": PRODUCTS[key]["sellingPrice"], "unit": dict(PRODUCTS[key])}
        for key, qty in case["lines"]
    ]


def _totals(case: dict) -> dict[str, float]:
    grand = _money(sum(PRODUCTS[key]["sellingPrice"] * qty for key, qty in case["lines"]))
    net = _money(grand / 1.12)
    return {"grandTotal": grand, "netOfVat": net, "vatTotal": _money(grand - net)}


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


def build(as_of: datetime) -> dict[str, list[dict]]:
    """Every planted document, grouped by out/ collection name."""
    data: dict[str, list[dict]] = {
        "ecommerce_sales_orders": [],
        "ecommerce_payments": [],
        "ecommerce_customers": [],
        "ecommerce_users": [dict(s) for s in SELLERS] + [dict(CASHIER)],
        "accounting_sales_orders": [],
        "accounting_customers": [],
        "accounting_customer_payments": [],
        "accounting_users": [dict(s) for s in SELLERS] + [dict(CASHIER)],
        "warehouse_served_orders": [],
        "salesapp_sales": [],
        "salesapp_commissions": [],
        "salesapp_users": [{**s, "roles": ["seller"], "userType": "seller"} for s in SELLERS],
        "salesapp_customers": [],
    }
    for case in CASES:
        seller = dict(SELLERS[case["seller"]])
        times = _timeline(case, as_of)
        flags = _flags(case)
        totals = _totals(case)
        balances = _balances(case, as_of)
        customer_id = _customer_id(case)
        customer_name = case["customer"]
        email = email_from_name(customer_name)
        phone = f"0917 {400 + CASES.index(case):03d} {2200 + 7 * CASES.index(case):04d}"
        address = f"{12 + CASES.index(case)} Jakosalem St., Brgy. Kasambagan, Cebu City"
        created_by = {"user": seller, "date": times["ordered"]}
        lines = _lines(case)
        balance = 0.0 if flags["paid"] else totals["grandTotal"]
        notes = (
            [{"content": DISPUTE_NOTE, "createdDate": as_of - timedelta(days=5), "userName": CASHIER["name"]}]
            if case["kind"] == "dsp"
            else []
        )

        data["ecommerce_sales_orders"].append(
            {
                "_id": case["id"],
                "salesOrderReference": case["id"],
                "customerId": customer_id,
                "customerName": customer_name,
                "customerContactName": customer_name.split(" - ")[0],
                "customerBusinessName": customer_name.split(" - ")[-1],
                "contactDetails": {
                    "phone": phone,
                    "contactPerson": customer_name.split(" - ")[0],
                    "email": email,
                },
                "customerDeliveryAddress": {"addressName": address, "latitude": None, "longitude": None},
                "itemsOrderList": [{"quantity": line["quantity"], "unit": line["unit"]} for line in lines],
                "grandTotal": totals["grandTotal"],
                "grandTotalWithFreight": totals["grandTotal"],
                "vatTotal": totals["vatTotal"],
                "netOfVat": totals["netOfVat"],
                "status": "delivered" if flags["delivered"] else "pending",
                "paid": flags["paid"],
                "scannedOut": flags["delivered"],
                "orderDate": times["ordered"],
                "outForDeliveryAt": times["released"],
                "deliveredAt": times["delivered"],
                "invoiceNumber": _invoice_number(case),
                "invoiceNumberList": [_invoice_number(case)],
                "invoiceImageList": [],
                "paymentMethod": "GCash" if case["kind"] in ("pns", "ppc") else "Bank Transfer",
                "paymentDocuments": [],
                "userSellerEmail": seller["email"],
                "userCreatorEmail": seller["email"],
                "closedBy": seller if flags["delivered"] else None,
                "outForDeliveryBy": {
                    "_id": "DEMO-USER-WH-1",
                    "name": WAREHOUSE_USER,
                    "email": email_from_name(WAREHOUSE_USER),
                }
                if flags["delivered"]
                else None,
                "approvalHold": None,
                "feedbackToken": None,
                "createdBy": created_by,
            }
        )
        if times["paid"]:
            data["ecommerce_payments"].append(
                _payment(case, customer_id, totals["grandTotal"], times["paid"], "confirmed", seller)
            )
        if times["pending_payment"]:
            data["ecommerce_payments"].append(
                _payment(case, customer_id, totals["grandTotal"], times["pending_payment"], "pending", None)
            )
        data["ecommerce_customers"].append(
            {
                "_id": customer_id,
                "name": customer_name,
                "email": email,
                "phone": phone,
                "deliveryAddress": {"addressName": address, "latitude": None, "longitude": None},
                "paymentTerms": case["terms"],
                "accountingCustomerId": customer_id,
                "createdBy": created_by,
            }
        )

        accounting_customer = {
            "_id": customer_id,
            "name": customer_name,
            "contactDetails": {"address": address, "phone": phone, "email": email, "zipCode": None},
            "bir2303": {"tin": None, "registeredName": None, "photoOfBir2303orCOR": None},
            "paymentTerms": case["terms"],
            "accountBalance": balances,
            "notesList": notes,
            "accountManager": seller,
            "creditLimit": None,
            "businessName": customer_name.split(" - ")[-1],
            "createdBy": created_by,
        }
        data["accounting_customers"].append(accounting_customer)
        data["accounting_sales_orders"].append(
            {
                "_id": case["id"],
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
                "itemsOrderList": lines,
                "grandTotal": totals["grandTotal"],
                "netOfVat": totals["netOfVat"],
                "vatTotal": totals["vatTotal"],
                "amountToReceive": totals["grandTotal"],
                "balance": balance,
                "totalPaymentReceived": totals["grandTotal"] if flags["paid"] else 0.0,
                "paid": flags["paid"],
                "delivered": flags["delivered"],
                "deliveryDate": times["delivered"],
                "invoiceNumber": _invoice_number(case),
                "invoiceDate": times["ordered"],
                "invoiceImageList": [],
                "isFromEcommerce": True,
                "type": "salesOrder",
                "createdBy": created_by,
            }
        )
        if flags["paid"]:
            data["accounting_customer_payments"].append(
                {
                    "_id": case["id"].replace("DEMO-", "DEMO-CPAY-", 1),
                    "amount": totals["grandTotal"],
                    "imageProofsList": [],
                    "paymentMethod": {
                        "method": "GCash",
                        "description": "GCash transfer confirmed from the web store",
                    },
                    "isPostDatedCheck": False,
                    "postDatedCheckDate": None,
                    "orderReferenceOfPayment": case["id"],
                    "customer": {"_id": customer_id, "name": customer_name},
                    "createdBy": {"user": dict(CASHIER), "date": times["paid"]},
                }
            )

        if flags["delivered"]:
            data["warehouse_served_orders"].append(
                {
                    "_id": case["id"],
                    "customerName": customer_name,
                    "createdByUserName": WAREHOUSE_USER,
                    "createdDate": times["ordered"] + timedelta(hours=2),
                    "released": True,
                    "releaseDate": times["released"],
                    "deliveryDate": times["delivered"],
                    "itemsOrderList": [
                        {"quantity": line["quantity"], "unit": line["unit"]} for line in lines
                    ],
                    "deliveryList": [
                        {
                            "_id": case["id"].replace("DEMO-", "DEMO-DLV-", 1),
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
            "name": customer_name,
            "email": email,
            "listOfPhoneNumber": [phone],
            "accountBalance": balances,
        }
        data["salesapp_customers"].append({**sale_customer, "accountManager": seller})
        data["salesapp_sales"].append(
            {
                "_id": case["id"],
                "userSeller": seller,
                "userCreator": None,
                "customer": sale_customer,
                "date": times["ordered"],
                "paid": flags["paid"],
                "delivered": flags["delivered"],
                "closed": flags["paid"] and flags["delivered"],
                "closedAt": None,
                "totalSale": totals["grandTotal"],
                "orderList": lines,
                "involvedUserIds": [seller["_id"]],
            }
        )
        data["salesapp_commissions"].append(
            {
                "_id": case["id"].replace("DEMO-", "DEMO-COMM-", 1),
                "type": "seller",
                "saleReference": case["id"],
                "user": seller,
                "percentToSeller": 2.0,
                "percentToCreator": 0.0,
                "commissionsEarned": _money(totals["netOfVat"] * 0.02),
                "commissionClaimed": False,
                "commissionClaimId": None,
                "createdDate": times["ordered"] + timedelta(minutes=5),
                "pointsEarned": 0,
            }
        )
    return data


def _payment(
    case: dict, customer_id: str, amount: float, when: datetime, status: str, reviewer: dict | None
) -> dict:
    suffix = "" if status == "confirmed" else "-PENDING"
    return {
        "_id": case["id"].replace("DEMO-", "DEMO-PAY-", 1) + suffix,
        "salesOrderId": case["id"],
        "customerId": customer_id,
        "amount": amount,
        "modeOfPayment": "GCash",
        "screenshotUrl": None,
        "transactionReferenceNumber": f"{7000000000000 + CASES.index(case) * 1111:013d}",
        "transactionReferenceKey": f"{8000000000000 + CASES.index(case) * 2222:013d}",
        "paymentDate": when,
        "status": status,
        "createdAt": when,
        "createdByUserId": customer_id,
        "createdByUserEmail": email_from_name(case["customer"]),
        "reviewedByUserEmail": reviewer["email"] if reviewer else None,
        "reviewedAt": when + timedelta(minutes=30) if reviewer else None,
        "rejectionReason": None,
        "accountingPaymentResult": {"paid": True, "balance": 0.0} if status == "confirmed" else None,
    }


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
