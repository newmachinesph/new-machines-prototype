"""What a reviewer may read: email- and phone-like tokens hidden, and, for a network reviewer, no name of the
org the work is for."""

import re

HIDDEN = "Hidden"
THE_CUSTOMER = "the customer"

# An agent's free-text note or flag may quote the customer. Reviewers see neither email addresses nor phone
# numbers: an email-like token, and a run of 9 to 15 digits written as a phone number (a lone ISO date, an
# amount or an order number does not qualify), read "Hidden".
EMAIL_LIKE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_LIKE = re.compile(r"(?<![\w#$.,/-])\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
PHONE_DIGITS = range(9, 16)
# A letter or digit. The org's name is matched as a whole word: not inside a longer run of letters and digits.
# An underscore separates words here (unlike regex \b), so "ch_acme" still names "Acme".
_ALNUM = r"[^\W_]"
_ALNUM_CHAR = re.compile(_ALNUM)


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    return HIDDEN if sum(c.isdigit() for c in text) in PHONE_DIGITS else text


def redacted(text: str) -> str:
    """`text` with email-like and phone-like tokens shown as "Hidden"."""
    return PHONE_LIKE.sub(_phone, EMAIL_LIKE.sub(HIDDEN, text))


def _name_pattern(name: str) -> re.Pattern[str]:
    """The org's name, any case, as a whole word: a boundary on each side where the name starts or ends with a
    letter or digit, so an org called "Al" leaves "Always" alone."""
    start = f"(?<!{_ALNUM})" if _ALNUM_CHAR.match(name[0]) else ""
    end = f"(?!{_ALNUM})" if _ALNUM_CHAR.match(name[-1]) else ""
    return re.compile(f"{start}{re.escape(name)}{end}", re.IGNORECASE)


def without_name(text: str, org_name: str | None) -> str:
    """`text` with the org's name (any case, as a whole word) read as "the customer"."""
    name = (org_name or "").strip()
    return _name_pattern(name).sub(THE_CUSTOMER, text) if name else text


def scrub(text: str, org_name: str | None) -> str:
    """`text` as a network reviewer reads it: the org's name (any case, as a whole word) reads "the
    customer", then email- and phone-like tokens read "Hidden"."""
    return redacted(without_name(text, org_name))
