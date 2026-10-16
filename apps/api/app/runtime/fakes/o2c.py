"""Fake triage, collections writer and report agents for the Order-to-Cash Exception Desk pack, following
skills/classify-orders.md, skills/write-reminders.md and skills/write-report.md."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.runtime.fakes._shared import day, has_word

KINDS = ("paid_not_shipped", "shipped_not_paid", "payment_pending_confirmation", "disputed")
CURRENCY = "PHP"
SIGN_OFF_LIMIT_MINOR = 2_000_000  # balances above ₱20,000 need finance's sign-off before any message
WAREHOUSE_WORKING_DAYS = 2  # a paid order not released after this many working days gets a note
DEFAULT_GRACE_DAYS = 7
_DISPUTE_WORDS = ("dispute", "disputes", "disputed", "credit memo")
_LABELS = {  # kind -> (one, many)
    "payment_pending_confirmation": ("payment pending confirmation", "payments pending confirmation"),
    "shipped_not_paid": ("shipped but not paid past terms", "shipped but not paid past terms"),
    "paid_not_shipped": ("paid but not shipped", "paid but not shipped"),
    "disputed": ("disputed invoice", "disputed invoices"),
}
_ACTIONS = {
    "confirm_payment": "confirm the payment in accounting",
    "escalate_finance": "flag for finance",
    "nudge_warehouse": "warehouse note",
    "none": "watch: inside the warehouse window",
}


def _records(value, key: str) -> list[dict]:
    """The connector's envelope ({"orders": [...]}) or a bare list."""
    items = value.get(key) if isinstance(value, dict) else value
    return [r for r in items or [] if isinstance(r, dict)]


def _minor(amount) -> int:
    try:
        return int((Decimal(str(amount or 0)) * 100).to_integral_value())
    except InvalidOperation, ValueError:
        return 0


def pesos(minor: int) -> str:
    return f"₱{minor // 100:,}.{minor % 100:02d}"


def _working_days(start: date, end: date) -> int:
    """Weekdays after `start` up to and including `end`."""
    count, current = 0, start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _manager(customer: dict, sale: dict, order: dict) -> tuple[str | None, str | None]:
    """Accounting's account manager, else the sales app seller, else the store's seller email."""
    if customer.get("account_manager"):
        return str(customer["account_manager"]), customer.get("account_manager_email") or None
    if sale.get("seller_name") or sale.get("seller_email"):
        return sale.get("seller_name") or None, sale.get("seller_email") or None
    if order.get("seller_email"):
        return None, str(order["seller_email"])
    return None, None


def _classify(so: dict, joined: dict, as_of: date, grace: int) -> tuple | None:
    """(kind, action, evidence, amount_minor, reference_date) for a broken order, else None."""
    oid = so["id"]
    order, customer, served = joined["order"], joined["customer"], joined["served"]
    terms = int(customer.get("payment_terms_days", so.get("payment_terms_days") or 0) or 0)
    balance = _minor(so.get("balance"))
    paid = balance == 0 or so.get("paid") is True
    delivered = so.get("delivered") is True or served.get("delivered") is True
    released = served.get("released") is True
    invoice_day = day(so.get("invoice_date")) or day(so.get("created_at"))
    order_day = day(order.get("order_date")) or invoice_day
    invoice = str(so.get("invoice_number") or oid)
    delivered_on = day(so.get("delivery_date") or served.get("delivered_at"))
    age = (as_of - date.fromisoformat(invoice_day)).days
    past_due = age - terms
    pending = [p for p in joined["payments"] if p.get("status") == "pending"]
    terms_text = f"{terms}-day terms" if terms else "payment on delivery"
    if balance > 0 and any(has_word(n, *_DISPUTE_WORDS) for n in customer.get("notes") or []):
        evidence = (
            f"Accounting invoice {invoice} ({terms_text}) is {past_due} days past due with a balance of "
            f"{pesos(balance)}, but the customer's account notes record a dispute and a pending credit memo: "
            "no reminder."
        )
        return "disputed", "escalate_finance", evidence, balance, invoice_day
    if balance > 0 and pending:
        p = pending[0]
        evidence = (
            f"Accounting invoice {invoice} shows a balance of {pesos(balance)}, but the store has a pending "
            f"{p.get('mode_of_payment') or 'store'} payment of {pesos(_minor(p.get('amount')))} created on "
            f"{day(p.get('created_at'))}: confirm it in accounting before any reminder."
        )
        return "payment_pending_confirmation", "confirm_payment", evidence, balance, invoice_day
    if delivered and balance > 0 and age > terms + grace:
        evidence = (
            f"Warehouse delivered {oid} on {delivered_on or 'an unrecorded day'} and Accounting invoice "
            f"{invoice} ({terms_text}) still shows the full balance of {pesos(balance)}, {past_due} days "
            f"past due and beyond the {grace}-day grace."
        )
        if balance > SIGN_OFF_LIMIT_MINOR:
            evidence += " Above ₱20,000, so finance's sign-off is needed before any message."
        action = "draft_collection_message" if customer.get("email") else "escalate_finance"
        return "shipped_not_paid", action, evidence, balance, invoice_day
    days = (as_of - date.fromisoformat(order_day)).days
    if paid and not delivered and (not served or not released) and days >= 1:
        confirmed = next((p for p in joined["payments"] if p.get("status") == "confirmed"), {})
        paid_on = day(confirmed.get("payment_date")) or order_day
        method = confirmed.get("mode_of_payment") or order.get("payment_method") or "a confirmed payment"
        working = _working_days(date.fromisoformat(order_day), as_of)
        where = "Warehouse has no served order" if not served else "Warehouse has not released it"
        evidence = (
            f"The store shows {oid} paid on {paid_on} ({method}, confirmed) and Accounting shows a zero "
            f"balance, but {where} after {_plural(working, 'working day')}."
        )
        action = "nudge_warehouse" if working > WAREHOUSE_WORKING_DAYS else "none"
        return "paid_not_shipped", action, evidence, _minor(so.get("grand_total")), order_day
    return None


def fake_triage(inputs: dict) -> dict:
    as_of = date.fromisoformat(str(inputs["as_of"]))
    grace = int(inputs.get("grace_days", DEFAULT_GRACE_DAYS) or 0)
    orders = {o.get("id"): o for o in _records(inputs.get("orders"), "orders")}
    customers = {c.get("id"): c for c in _records(inputs.get("customers"), "customers")}
    served = {s.get("id"): s for s in _records(inputs.get("served_orders"), "served_orders")}
    sales = {s.get("id"): s for s in _records(inputs.get("sales"), "sales")}
    payments: dict[str, list[dict]] = {}
    for p in _records(inputs.get("payments"), "payments"):
        payments.setdefault(p.get("order_id"), []).append(p)
    exceptions, clean = [], 0
    for so in _records(inputs.get("sales_orders"), "sales_orders"):
        oid = so.get("id")
        customer = customers.get(so.get("customer_id")) or {}
        joined = {
            "order": orders.get(oid) or {},
            "customer": customer,
            "served": served.get(oid) or {},
            "payments": payments.get(oid, []),
        }
        found = _classify({**so, "id": str(oid)}, joined, as_of, grace)
        if found is None:
            clean += 1
            continue
        kind, action, evidence, amount, reference = found
        terms = int(customer.get("payment_terms_days", so.get("payment_terms_days") or 0) or 0)
        invoice_day = day(so.get("invoice_date")) or day(so.get("created_at"))
        delivered_on = day(so.get("delivery_date") or joined["served"].get("delivered_at"))
        manager, manager_email = _manager(customer, sales.get(oid) or {}, joined["order"])
        exceptions.append(
            {
                "order_id": str(oid),
                "kind": kind,
                "customer_id": str(so.get("customer_id") or customer.get("id") or ""),
                "customer_name": str(customer.get("name") or so.get("customer_name") or ""),
                "customer_email": customer.get("email") or None,
                "invoice_number": so.get("invoice_number") or None,
                "amount_minor": amount,
                "currency": CURRENCY,
                "reference_date": reference,
                "due_date": None
                if kind == "paid_not_shipped"
                else (date.fromisoformat(invoice_day) + timedelta(days=terms)).isoformat(),
                "delivered_on": delivered_on or None,
                "days_outstanding": (as_of - date.fromisoformat(reference)).days,
                "account_manager": manager,
                "account_manager_email": manager_email,
                "evidence": evidence,
                "recommended_action": action,
            }
        )
    exceptions.sort(key=lambda e: (KINDS.index(e["kind"]), -e["days_outstanding"]))
    totals: dict = {k: {"count": 0, "amount_minor": 0} for k in KINDS}
    for e in exceptions:
        totals[e["kind"]]["count"] += 1
        totals[e["kind"]]["amount_minor"] += e["amount_minor"]
    totals["currency"] = CURRENCY
    big = [
        f"{e['order_id']} ({pesos(e['amount_minor'])})"
        for e in exceptions
        if e["kind"] == "shipped_not_paid" and e["amount_minor"] > SIGN_OFF_LIMIT_MINOR
    ]
    sign_off = ""
    if big:
        one = len(big) == 1
        sign_off = (
            f"{', '.join(big)} {'is' if one else 'are'} above ₱20,000 and {'needs' if one else 'need'} "
            f"finance's sign-off before {'its reminder goes' if one else 'their reminders go'} out."
        )
    checked = clean + len(exceptions)
    summary = (
        f"{_plural(checked, 'order')} checked across the store, the ledger, the warehouse and the sales app: "
        f"{clean} clean and {_plural(len(exceptions), 'exception')}."
    )
    if exceptions:
        parts = [
            f"{totals[k]['count']} {_LABELS[k][0 if totals[k]['count'] == 1 else 1]} "
            f"({pesos(totals[k]['amount_minor'])})"
            for k in _LABELS
            if totals[k]["count"]
        ]
        summary += " Found: " + "; ".join(parts) + "."
    else:
        summary += " Every order agrees across the four systems."
    return {
        "summary": summary,
        "exceptions": exceptions,
        "clean_count": clean,
        "totals": totals,
        "sign_off_note": sign_off,
    }


def fake_collections_writer(inputs: dict) -> dict:
    """The largest reminders, at most max_messages, per the write-reminders skill."""
    company = str(inputs.get("company_name") or "our company")
    cap = int(inputs.get("max_messages", 3))
    exceptions = sorted(inputs.get("exceptions") or [], key=lambda e: -int(e.get("amount_minor") or 0))
    drafts = []
    for e in exceptions[:cap]:
        name = str(e.get("customer_name") or "Customer").split(" - ")[0]
        manager = str(e.get("account_manager") or f"{company} Accounts")
        invoice = str(e.get("invoice_number") or e.get("order_id"))
        reference, due = str(e.get("reference_date") or ""), str(e.get("due_date") or "")
        terms = (date.fromisoformat(due) - date.fromisoformat(reference)).days if reference and due else 0
        past_due = int(e.get("days_outstanding") or 0) - terms
        terms_text = f"with payment terms of {terms} days" if terms else "with payment due on delivery"
        delivered = str(e.get("delivered_on") or "the recorded delivery date")
        sign_off = ["Maraming salamat po,", manager, f"Account Manager, {company}"]
        if e.get("account_manager_email"):
            sign_off.append(str(e["account_manager_email"]))
        body = (
            f"Dear {name},\n\n"
            f"Good day! This is a friendly reminder from {company} regarding Invoice {invoice} for order "
            f"{e.get('order_id')}, amounting to {pesos(int(e.get('amount_minor') or 0))}.\n\n"
            f"The goods were delivered on {delivered}, {terms_text} (due {due or 'on delivery'}), and the "
            f"invoice is now {past_due} days past due.\n\n"
            "If payment has already been made, kindly disregard this message and send us the payment "
            "reference so we can post it right away; otherwise, we would appreciate settlement at your "
            "earliest convenience.\n\n"
            "Thank you very much for your continued business.\n\n" + "\n".join(sign_off)
        )
        drafts.append(
            {
                "to": str(e.get("customer_email") or ""),
                "subject": f"Payment reminder: Invoice {invoice} for order {e.get('order_id')}"[:150],
                "body": body[:4000],
                "order_id": str(e.get("order_id")),
                "account_manager": manager,
            }
        )
    return {"drafts": drafts}


def fake_report(inputs: dict) -> dict:
    """The report per the write-report skill: the triage's numbers, what was written, a row per exception."""
    triage = inputs.get("triage") or {}
    drafts = [d for d in inputs.get("drafts") or [] if isinstance(d, dict)]
    approval = inputs.get("approval") if isinstance(inputs.get("approval"), dict) else None
    created = int(inputs.get("drafts_created") or 0)
    finance, warehouse = int(inputs.get("finance_notes") or 0), int(inputs.get("warehouse_notes") or 0)
    sent = approval is not None and approval.get("decision") == "granted" and created == len(drafts)
    drafted = {d.get("order_id") for d in drafts} if sent else set()
    rows = []
    for e in triage.get("exceptions") or []:
        action = e.get("recommended_action")
        if action == "draft_collection_message":
            text = f"collection reminder from {e.get('account_manager') or 'the Accounts desk'}"
        else:
            text = _ACTIONS.get(action, str(action))
        if action == "none":
            outcome = "listed"
        elif not sent:
            outcome = "not_sent"
        elif action == "draft_collection_message":
            outcome = "drafted" if e.get("order_id") in drafted else "not_sent"
        else:
            outcome = "noted"
        rows.append(
            {
                "order_id": str(e.get("order_id")),
                "kind": e.get("kind"),
                "customer_name": str(e.get("customer_name") or ""),
                "amount_minor": int(e.get("amount_minor") or 0),
                "currency": str(e.get("currency") or CURRENCY),
                "days_outstanding": int(e.get("days_outstanding") or 0),
                "action": text,
                "outcome": outcome,
                "note": str(e.get("evidence") or ""),
            }
        )
    summary = str(triage.get("summary") or "")
    if not rows:
        summary += " Nothing was due, so nothing was sent or posted."
    elif sent:
        summary += (
            f" {_plural(created, 'reminder')} {'was' if created == 1 else 'were'} saved as Gmail drafts, "
            f"{_plural(finance, 'note')} posted for finance and {_plural(warehouse, 'note')} for the "
            "warehouse."
        )
    else:
        summary += " Nothing was sent or posted: the approval was not granted."
    return {
        "summary": summary,
        "sent": sent,
        "clean_count": int(triage.get("clean_count") or 0),
        "totals": triage.get("totals") or {},
        "actions": {"reminders_drafted": created, "finance_notes": finance, "warehouse_notes": warehouse},
        "rows": rows,
    }


AGENTS = {
    "o2c-triage-agent": fake_triage,
    "collections-writer": fake_collections_writer,
    "o2c-report-agent": fake_report,
}
JEV: dict = {}
