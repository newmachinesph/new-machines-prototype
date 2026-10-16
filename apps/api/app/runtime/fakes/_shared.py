"""Pure helpers the fake sample-pack scripts share."""

import re
from decimal import Decimal, InvalidOperation

_ADDRESS = re.compile(r"<\s*([^<>\s]+@[^<>\s]+)\s*>")


def sender(text: str) -> tuple[str, str]:
    """("Maya Chen", "maya@x.example.com") from "Maya Chen <maya@x.example.com>"; ("", address) when bare."""
    text = str(text or "").strip()
    found = _ADDRESS.search(text)
    if found is None:
        return "", text
    return text[: found.start()].strip().strip('"'), found.group(1)


def messages(value) -> list[dict]:
    """The emails of a Gmail list result ({"messages": [...]}) or of a bare list."""
    items = value.get("messages") if isinstance(value, dict) else value
    return [m for m in items or [] if isinstance(m, dict)]


def day(timestamp: str) -> str:
    return str(timestamp or "")[:10]


def money_minor(text) -> int | None:
    """ "48.50", "$1,234.5" or "615" as cents; None when it is not an amount."""
    cleaned = str(text or "").replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return int((amount * 100).to_integral_value())


def money_text(minor: int, currency: str = "USD") -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d} {currency}"


def has_word(text, *words: str) -> bool:
    lowered = str(text or "").lower()
    return any(re.search(rf"\b{re.escape(word.lower())}\b", lowered) for word in words)


def field(text: str, label: str) -> str:
    """The value of a "Label: value" line in a decision-model state text."""
    prefix = f"{label}: "
    for line in str(text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""
