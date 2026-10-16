"""Fake expense-agent for the Weekly Expense Check pack, following skills/check-expenses.md."""

from datetime import date, timedelta

from app.runtime.fakes._shared import has_word, money_minor, money_text

CATEGORIES = ("Travel", "Meals", "Software", "Office", "Other")
_WORDS = {
    "Travel": ("flight", "train", "taxi", "hotel", "parking", "mileage"),
    "Meals": ("lunch", "dinner", "breakfast", "coffee", "meal"),
    "Software": ("subscription", "software", "licence", "license", "plan", "app"),
    "Office": ("paper", "toner", "printer", "desk", "chair", "stationery", "supplies"),
}
RECEIPT_FROM_MINOR = 2500
LIMIT_MINOR = 50000
DUPLICATE_DAYS = 7
CURRENCY = "USD"


def _category(description: str) -> str:
    return next((c for c, words in _WORDS.items() if has_word(description, *words)), "Other")


def _dollars(minor: int) -> str:
    return money_text(minor, CURRENCY).removesuffix(f" {CURRENCY}")


def _items(count: int) -> str:
    return "1 item" if count == 1 else f"{count} items"


def _rows(sheet) -> list[dict]:
    ranges = (sheet or {}).get("valueRanges") if isinstance(sheet, dict) else None
    values = (ranges[0].get("values") if ranges else None) or []
    rows = []
    for number, cells in enumerate(values[1:], start=2):
        cells = [str(c) for c in cells] + [""] * 5
        amount = money_minor(cells[2])
        if amount is None or len(cells[0]) < 10:
            continue
        rows.append(
            {
                "row": number,
                "date": cells[0][:10],
                "description": cells[1].strip() or "No description",
                "amount_minor": amount,
                "receipt": cells[4].strip().lower() in ("yes", "y", "true"),
            }
        )
    return rows


def _flag(expense: dict, earlier: list[dict]) -> tuple[str, str] | None:
    amount = expense["amount_minor"]
    if amount > LIMIT_MINOR:
        return (
            "Over the $500 limit",
            f"{money_text(amount)} is more than the 500.00 USD limit for one expense.",
        )
    if amount >= RECEIPT_FROM_MINOR and not expense["receipt"]:
        return "No receipt for $25 or more", "Expenses of 25.00 USD or more need a receipt."
    day = date.fromisoformat(expense["date"])
    for other in earlier:
        same = (
            other["description"].casefold() == expense["description"].casefold()
            and other["amount_minor"] == amount
        )
        if same and (day - date.fromisoformat(other["date"])).days <= DUPLICATE_DAYS:
            return (
                f"Possible duplicate of row {other['row']}",
                "Same description and amount as an earlier expense.",
            )
    return None


def fake_expenses(inputs: dict) -> dict:
    start = date.fromisoformat(str(inputs["week_start"]))
    end = start + timedelta(days=6)
    week = [r for r in _rows(inputs.get("sheet")) if start.isoformat() <= r["date"] <= end.isoformat()]
    expenses, review_items = [], []
    for expense in week:
        flagged = _flag(expense, expenses)
        expenses.append({**expense, "category": _category(expense["description"])})
        if flagged is not None:
            flag, note = flagged
            review_items.append(
                {
                    "ref": f"Row {expense['row']}",
                    "date": expense["date"],
                    "amount_minor": expense["amount_minor"],
                    "currency": CURRENCY,
                    "flag": flag,
                    "note": note,
                }
            )
    categories = []
    for name in CATEGORIES:
        of = [e for e in expenses if e["category"] == name]
        if of:
            categories.append(
                {"category": name, "count": len(of), "amount_minor": sum(e["amount_minor"] for e in of)}
            )
    total = sum(e["amount_minor"] for e in expenses)
    week_start, week_end = start.isoformat(), end.isoformat()
    rows, facts = [], []
    if expenses:
        rows = [[week_start, c["category"], str(c["count"]), _dollars(c["amount_minor"])] for c in categories]
        rows.append([week_start, "Total", str(len(expenses)), _dollars(total)])
        period = f"Expenses from {week_start} to {week_end}"
        facts = [f"{period}: {_items(len(expenses))}, {money_text(total)} in total."]
        facts += [
            f"{c['category']}: {_items(c['count'])}, {money_text(c['amount_minor'])}." for c in categories
        ]
        if review_items:
            listed = "; ".join(f"{i['ref']} ({i['flag']})" for i in review_items)
            flagged = "1 expense is" if len(review_items) == 1 else f"{len(review_items)} expenses are"
            facts.append(f"{flagged} flagged for a check: {listed}.")
        else:
            facts.append("No expense needed a check.")
        noun = "expense" if len(expenses) == 1 else "expenses"
        summary = (
            f"{len(expenses)} {noun} from {week_start} to {week_end}, {money_text(total)} in total; "
            f"{len(review_items)} flagged for a check."
        )
    else:
        summary = f"No expenses were found from {week_start} to {week_end}."
    return {
        "summary": summary,
        "week_start": week_start,
        "week_end": week_end,
        "currency": CURRENCY,
        "total_minor": total,
        "expenses": [
            {k: e[k] for k in ("row", "date", "description", "category", "amount_minor", "receipt")}
            for e in expenses
        ],
        "categories": categories,
        "review_items": review_items,
        "summary_rows": rows,
        "email_facts": facts,
    }


AGENTS = {"expense-agent": fake_expenses}
JEV: dict = {}
