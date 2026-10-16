"""Synthetic background orders for the sandbox fixtures (pure functions, no database, no key).

The orders around the planted `DEMO-*` cases are invented here from the generator's name lists with a
fixed seed, so the committed fixtures hold nothing derived from a real business: random customers and
sellers, random order moments (any time of a working day inside the 30 days before `as_of`), random
quantities of the generic catalogue items, and ids of the shapes a business app produces. Every order is
consistent across the four systems and clean for the pack (paid and delivered, or delivered and still
inside its payment terms), except `OVERDUE` orders: delivered, unpaid, past terms, with no account
manager and no email on file, so the pack's fallback to the sales app seller is exercised
(`DEMO_CASES.md`, "Everything else"). `build` returns the documents grouped like `plant.build`.
"""

import random
import string
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import anonymize
import plant

SEED = 20261016
COUNT = 25
OVERDUE = 1
WINDOW_DAYS = 30
# Orders are placed between these many days before `as_of`, so every event (delivery, payment) is over.
OLDEST_DAYS = 29.5
NEWEST_DAYS = 3.5
BUSINESS_HOURS_UTC = range(0, 11)  # 08:00 to 18:59 Manila
SELLER_COUNT = 3
OPEN_SHARE = 0.2  # delivered orders still inside their payment terms
TERMS = (0, 0, 0, 15, 30)
QUANTITIES = (50, 100, 120, 150, 200, 240, 300, 400, 500, 600, 750, 800, 1000, 1200, 1500, 2000)
SMALL_PRODUCTS = ("b", "c", "d", "e")  # at most 6.00 x 240 = 1,440, below the smallest planted reminder
# Store payment mode -> ledger method; a cash payment has no reference and no dated store receipt.
PAYMENT_MODES = {"GCash": "mobile wallet", "Bank Transfer": "bank", "Cash": "cash"}
CASH = "Cash"

DIGITS = string.digits
LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
ALNUM = DIGITS + LOWER + UPPER
HEX = DIGITS + "abcdef"
BASE64URL = ALNUM + "-_"
IdMaker = Callable[[random.Random], str]


def _long(length: int, alphabet: str) -> IdMaker:
    return lambda rng: "".join(rng.choice(alphabet) for _ in range(length))


def _short(letters: int, digits: int) -> IdMaker:
    def make(rng: random.Random) -> str:
        head = "".join(rng.choice(UPPER) for _ in range(letters))
        return f"{head}-{rng.randrange(10 ** (digits - 1), 10**digits)}"

    return make


def _any(*makers: IdMaker) -> IdMaker:
    return lambda rng: rng.choice(makers)(rng)


# Id shapes of a business app backed by auth providers and MongoDB (digests, uids, ObjectIds, references).
LONG_IDS: dict[str, IdMaker] = {
    "order": _long(43, BASE64URL),
    "customer": _any(_long(20, DIGITS + LOWER), _long(28, ALNUM), _long(43, BASE64URL)),
    "invoice": _long(14, DIGITS + UPPER),
    "payment": _long(43, BASE64URL),
    "ledger_payment": _long(32, ALNUM),
    "delivery": _long(24, HEX),
    "commission": _long(20, DIGITS + LOWER),
    "user": _long(28, ALNUM),
    "reference": _long(13, DIGITS),
}
# Short human-readable ids for the connector's two-row samples.
SHORT_IDS: dict[str, IdMaker] = {
    "order": _short(3, 6),
    "customer": _short(4, 4),
    "invoice": lambda rng: f"{_short(3, 4)(rng)}-{rng.randrange(1000, 10000)}",
    "payment": _short(3, 4),
    "ledger_payment": _short(2, 4),
    "delivery": _short(3, 2),
    "commission": _short(3, 4),
    "user": _short(3, 4),
    "reference": _short(5, 6),
}


def _moment(rng: random.Random, as_of: datetime, oldest: float, newest: float) -> datetime:
    """A business-hours moment between `oldest` and `newest` days before `as_of`, to the second."""
    day = (as_of - timedelta(days=rng.uniform(newest, oldest))).date()
    clock = (rng.choice(BUSINESS_HOURS_UTC), rng.randrange(60), rng.randrange(60))
    return datetime(day.year, day.month, day.day, *clock, tzinfo=as_of.tzinfo)


def _phone(rng: random.Random) -> str:
    return f"{anonymize.FICTIONAL_PHONE_PREFIX}{rng.randrange(10000):04d}"


def _customer_name(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.35:
        return anonymize.random_person_name(rng)
    if roll < 0.65:
        return anonymize.random_business_name(rng)
    return f"{anonymize.random_person_name(rng)} - {anonymize.random_business_name(rng)}"


def _sellers(rng: random.Random, ids: dict[str, IdMaker]) -> list[dict]:
    return [plant.user(ids["user"](rng), anonymize.random_person_name(rng)) for _ in range(SELLER_COUNT)]


def _customers(rng: random.Random, ids: dict[str, IdMaker], count: int, managers: list[dict]) -> list[dict]:
    """Customers with contact details on file only sometimes (the ledger rarely records a manager)."""
    customers = []
    for _ in range(count):
        name = _customer_name(rng)
        customers.append(
            {
                "_id": ids["customer"](rng),
                "name": name,
                "email": anonymize.email_from_name(name) if rng.random() < 0.4 else None,
                "phone": _phone(rng) if rng.random() < 0.4 else None,
                "address": anonymize.random_address(rng),
                "terms": rng.choice(TERMS),
                "manager": rng.choice(managers) if rng.random() < 0.2 else None,
                "notes": [],
                "balances": {"current": 0.0, "overdue": 0.0},
            }
        )
    return customers


def _lines(rng: random.Random, small: bool = False) -> list[dict]:
    """One to three catalogue lines; `small` keeps the total under the smallest planted reminder."""
    if small:
        return plant.lines_of([(rng.choice(SMALL_PRODUCTS), rng.choice(QUANTITIES[:6]))])
    keys = rng.sample(sorted(plant.PRODUCTS), k=rng.choice((1, 1, 2, 3)))
    return plant.lines_of([(key, rng.choice(QUANTITIES)) for key in keys])


def _order(
    rng: random.Random,
    ids: dict[str, IdMaker],
    as_of: datetime,
    kind: str,
    customer: dict,
    sellers: list[dict],
    staff: tuple[dict, dict],
) -> dict[str, Any]:
    """The explicit description `plant.order_documents` builds a background order from.

    `kind`: `closed` (paid and delivered), `open` (delivered, unpaid, inside its terms) or `overdue`
    (delivered, unpaid, past terms and the pack's grace, no manager or email on file).
    """
    warehouse_user, cashier = staff
    seller = rng.choice(sellers)
    if kind == "open":
        terms = rng.choice((15, 30))
        ordered = _moment(rng, as_of, min(terms, OLDEST_DAYS), NEWEST_DAYS)
        customer = {**customer, "terms": terms}
    elif kind == "overdue":
        ordered = _moment(rng, as_of, OLDEST_DAYS, 20)
        customer = {**customer, "terms": 0, "manager": None, "email": None}
    else:
        ordered = _moment(rng, as_of, OLDEST_DAYS, NEWEST_DAYS)
    released = ordered + timedelta(hours=rng.uniform(3, 50))
    delivered = released + timedelta(hours=rng.uniform(2, 9))
    lines = _lines(rng, small=kind == "overdue")
    total = plant.totals_of(lines)["grandTotal"]
    paid = kind == "closed"
    mode = rng.choice(sorted(PAYMENT_MODES)) if paid else rng.choice(("GCash", "Bank Transfer"))
    payments, ledger_payments = [], []
    if paid:
        paid_at = ordered + timedelta(hours=rng.uniform(0.5, 70))
        payments.append(
            {
                "_id": ids["payment"](rng),
                "amount": total,
                "mode": mode,
                "when": paid_at,
                "status": "confirmed",
                "reviewer": seller,
                "reference": None if mode == CASH else ids["reference"](rng),
                "key": None if mode == CASH else ids["reference"](rng),
                "dated": mode != CASH,
            }
        )
        ledger_payments.append(
            {
                "_id": ids["ledger_payment"](rng),
                "amount": total,
                "method": PAYMENT_MODES[mode],
                "description": None,
                "when": paid_at + timedelta(minutes=rng.uniform(10, 300)),
            }
        )
    closed_at = max(delivered, ledger_payments[0]["when"]) if paid else None
    return {
        "id": ids["order"](rng),
        "reference": ids["invoice"](rng),
        "invoice_number": ids["invoice"](rng),
        "customer": customer,
        "seller": seller,
        "warehouse_user": warehouse_user,
        "cashier": cashier,
        "lines": lines,
        "paid": paid,
        "delivered": True,
        "status": "closed" if paid else "delivered",
        "payment_method": mode,
        "times": {
            "ordered": ordered,
            "created": ordered + timedelta(minutes=rng.uniform(5, 90)),
            "released": released,
            "delivered": delivered,
            "closed": closed_at,
        },
        "payments": payments,
        "ledger_payments": ledger_payments,
        "commission": {"_id": ids["commission"](rng)},
        "delivery_id": ids["delivery"](rng),
    }


def _with_balances(orders: list[dict], as_of: datetime) -> list[dict]:
    """Each customer's open balance is the sum of its unpaid orders; overdue the part past its terms."""
    open_by_customer: dict[str, dict[str, float]] = {}
    for order in orders:
        if order["paid"]:
            continue
        customer = order["customer"]
        total = plant.totals_of(order["lines"])["grandTotal"]
        age = (as_of - order["times"]["ordered"]).days
        balances = open_by_customer.setdefault(customer["_id"], {"current": 0.0, "overdue": 0.0})
        balances["current"] = plant.money(balances["current"] + total)
        if age > customer["terms"]:
            balances["overdue"] = plant.money(balances["overdue"] + total)
    return [
        {
            **order,
            "customer": {
                **order["customer"],
                "balances": open_by_customer.get(order["customer"]["_id"], {"current": 0.0, "overdue": 0.0}),
            },
        }
        for order in orders
    ]


def build(
    as_of: datetime,
    count: int = COUNT,
    overdue: int = OVERDUE,
    seed: int = SEED,
    ids: dict[str, IdMaker] = LONG_IDS,
) -> dict[str, list[dict]]:
    """`count` synthetic orders (of which `overdue` are overdue) with their customers, sellers and staff."""
    rng = random.Random(seed)
    ids = dict(ids)
    staff = (
        plant.user(ids["user"](rng), anonymize.random_person_name(rng)),
        plant.user(ids["user"](rng), anonymize.random_person_name(rng)),
    )
    sellers = _sellers(rng, ids)
    customers = _customers(rng, ids, count, sellers)  # one customer per order, so its terms are one thing
    kinds = ["overdue"] * overdue + ["open"] * max(0, round((count - overdue) * OPEN_SHARE))
    kinds += ["closed"] * (count - len(kinds))
    rng.shuffle(kinds)
    orders = [
        _order(rng, ids, as_of, kind, customer, sellers, staff)
        for kind, customer in zip(kinds, customers, strict=True)
    ]
    orders = _with_balances(orders, as_of)
    return plant.merge(plant.user_documents(sellers, list(staff)), *map(plant.order_documents, orders))


def order_ids(data: dict[str, list[dict]]) -> set[str]:
    return {str(doc["_id"]) for doc in data.get("ecommerce_sales_orders", [])}
