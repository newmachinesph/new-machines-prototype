"""Keyed anonymiser for the Order-to-Cash demo dataset (pure functions, no database).

Every fake value is derived with HMAC-SHA256 under a secret key read from the environment variable
`DEMO_ANON_KEY` (never committed; without it nothing runs), so the same real customer, user, phone,
address, id or invoice number becomes the same fake one in all four source systems and the joins (`_id`,
order references, customer ids) survive, while nobody without the key can rebuild or brute-force the
mapping. Every timestamp moves forward by one secret number of days (also derived from the key; the
export reads a window that ended that many days ago, so the demo looks current) and then back by an
offset that differs per order chain (whole days plus a time of day), so no real date or time survives
and no single delta links the two; the events of one order keep their sequence. Every amount of a chain
is scaled by one chain-specific factor (0.8 to 1.2), and unit cost prices are dropped. Each collection
has a SHAPE below that lists the fields kept from the source document and the handler applied to each;
everything not listed is dropped, which is how the giant embedded unit documents, images, signatures and
roles never reach the export. Free text is replaced by fixed values, and a final pass scrubs any string
that still looks like an email, phone number or URL.
"""

import hashlib
import hmac
import os
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

KEY_ENV = "DEMO_ANON_KEY"
MIN_KEY_CHARS = 16
# Every fake phone is `+63 900 000 XXXX`: a number range that is not assigned to any carrier.
FICTIONAL_PHONE_PREFIX = "+63 900 000 "
SHIFT_DAYS_MIN = 30
SHIFT_DAYS_MAX = 150
# Each order chain additionally moves back by up to this many whole days plus a random time of day.
JITTER_DAYS_MAX = 14
AMOUNT_FACTOR_MIN = 0.8
AMOUNT_FACTOR_MAX = 1.2
# A clearly fictional business: "Demo" is in the name, and the address and phone cannot be reached.
MY_BUSINESS = {
    "name": "Kalumpang Demo Supply Co.",
    "contactDetails": {
        "address": "1 Sample Street, Example Industrial Park, Sampletown",
        "phone": f"{FICTIONAL_PHONE_PREFIX}0100",
        "email": "orders@kalumpang-demo.example.com",
    },
}
# Fixed replacements for free text that can name real people, places or disputes.
HOLD_REASON = "Held for review"
REJECTION_REASON = "Rejected by reviewer"
PRODUCT_CATEGORY = "General"

FIRST_NAMES = [
    "Andres", "Bea", "Carlo", "Dianne", "Emilio", "Francine", "Gabriel", "Hazel", "Ivan", "Joanna",
    "Kristoffer", "Liza", "Marco", "Nadia", "Oliver", "Patricia", "Rafael", "Sheila", "Teodoro", "Vanessa",
    "Winston", "Ysabel", "Alvin", "Bernadette", "Christian", "Dolores", "Edgardo", "Felicity", "Gerald",
    "Hannah", "Isidro", "Jasmine", "Kevin", "Lorna", "Miguel", "Nenita", "Oscar", "Pilar", "Rodrigo",
    "Susana", "Teresa", "Ulysses", "Vicente", "Wilma", "Zenaida", "Angelo", "Benjie", "Cristina", "Dennis",
    "Elaine", "Ferdinand", "Gina", "Henry", "Irene", "Jerome", "Karen", "Lorenzo", "Marites", "Noel",
    "Precious", "Ronaldo", "Sofia", "Jun", "Mae", "Paolo", "Rhea", "Tonyo", "Yvette",
]  # fmt: skip
SURNAMES = [
    "Abad", "Bautista", "Cruz", "Dela Cruz", "Domingo", "Espiritu", "Fernandez", "Garcia", "Hernandez",
    "Ignacio", "Javier", "Lim", "Macaraeg", "Navarro", "Ocampo", "Pascual", "Quiambao", "Ramos", "Santos",
    "Tolentino", "Uy", "Villanueva", "Yap", "Zamora", "Aquino", "Buenaventura", "Castillo", "Enriquez",
    "Flores", "Gonzales", "Hilario", "Jimenez", "Lacson", "Magbanua", "Nunez", "Ortega", "Perez", "Reyes",
    "Salazar", "Tan", "Valdez", "Ybanez", "Alcantara", "Borja", "Cabrera", "Delgado", "Evangelista",
    "Fajardo", "Galang", "Mendoza", "Manalo", "Padilla", "Rosales", "Sarmiento", "Torres", "Velasco",
    "Ong", "Sy", "Go", "Chua", "Aguilar", "Rivera", "Soriano", "Mercado", "Castro", "Dizon",
]  # fmt: skip
BUSINESS_PREFIXES = [
    "Sunrise", "Golden", "Island", "Harbor", "Mabuhay", "Lakeside", "Starlight", "Kalayaan", "Northgate",
    "Summit", "Blue Horizon", "Palm", "Coral", "Evergreen", "Rizal", "Mango Tree", "Silver Bell",
    "Twin Peaks", "Seaside", "Ridgeview", "Monarch", "Pearl", "Sampaguita", "Tropic", "Villa Verde",
    "Metro", "Riverbend", "Oceanic", "Southpoint", "Highland", "Marina", "Sunset", "Lucky Star",
    "Crown", "Garden City", "Pacific", "Bamboo", "Narra", "Acacia", "Maharlika",
]  # fmt: skip
BUSINESS_TYPES = [
    "Trading", "Minimart", "Bakery", "Cafe", "Catering", "Pharmacy", "Hardware", "Grocery", "Kitchen",
    "Eatery", "Store", "Enterprises", "Food Hub", "Printing", "Supply", "Canteen", "Bakeshop",
    "Water Refilling Station", "Lechon House", "Snack Bar", "Restaurant", "Meat Shop", "Pastry Shop",
    "Food Services",
]  # fmt: skip
# Place names found all over the country (heroes, saints, common barangay names), not one region's.
STREETS = [
    "Mabini", "Rizal", "Bonifacio", "Aguinaldo", "Luna", "Burgos", "Del Pilar", "Magsaysay", "Quezon",
    "Roxas", "Lopez Jaena", "Gomez", "Zamora", "Abad Santos", "Katipunan", "Osmena", "Lapu-Lapu",
    "Sampaguita", "Maharlika Highway", "National Highway",
]  # fmt: skip
BARANGAYS = [
    "Poblacion", "San Isidro", "San Roque", "San Jose", "Sta. Cruz", "Bagong Silang", "Maligaya",
    "Bagumbayan", "Centro", "San Antonio", "Sto. Nino", "San Vicente", "Pag-asa", "Mabini", "Rizal",
    "Dolores", "Burgos", "San Miguel", "Sta. Maria", "Kaunlaran", "San Nicolas", "Sta. Lucia",
]  # fmt: skip
CITIES = [
    "Quezon City", "Manila", "Davao City", "Cebu City", "Iloilo City", "Bacolod City", "Cagayan de Oro City",
    "Baguio City", "Zamboanga City", "Legazpi City", "Tacloban City", "Dagupan City", "Angeles City",
    "Naga City", "General Santos City", "Puerto Princesa City", "Batangas City", "Lucena City",
    "Tuguegarao City", "Butuan City",
]  # fmt: skip

PERSON_INITIALS = "ABCDEFGHJKLMNOPRSTV"
BUSINESS_RE = re.compile(
    r"\b(corp(oration)?|inc|co|company|store|cafe|caf[eé]|shop|trading|services?|pharmacy|drugstore|"
    r"mini ?mart|office|kitchen|bakery|bakeshop|restaurant|resto|enterprises?|ent|hardware|grocery|"
    r"sari-?sari|supply|supplies|catering|foods?|hotel|resort|school|university|college|clinic|hospital|"
    r"market|mart|center|centre|depot|ltd|llc|opc|builders|construction|motors|farm|printing|canteen|"
    r"eatery|lechon|bbq|grill|dental|laundry|water|refilling|station|marketing|ventures|trade|traders|"
    r"industries|industrial|manufacturing|mfg|distributor|distribution|packaging|logistics|cooperative|"
    r"coop|association|assn|foundation|bar|lounge|diner|pizzeria|bistro|gas|fuel|agri|agrivet|poultry)\b",
    re.IGNORECASE,
)
PERSON_BUSINESS_SPLIT = re.compile(r"\s+[-–—]\s+")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"\b(?:https?|gs|ftp)://\S+|\bwww\.\S+", re.IGNORECASE)
FICTIONAL_PHONE_RE = re.compile(r"\+63 900 000 \d{4}")
PHONE_RE = re.compile(
    r"(?:\+?63|\b0)\s?9\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b"  # PH mobile, with or without country code
    r"|\(?\b\d{2,3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"  # landline written with separators
    r"|\b09\d{9}\b"  # bare 11-digit mobile
)
# Keys whose string values are identifiers; the scrub pass leaves them alone.
ID_KEYS = frozenset(
    {
        "_id",
        "salesOrderReference",
        "salesOrderId",
        "customerId",
        "orderReferenceOfPayment",
        "saleReference",
        "invoiceNumber",
        "invoiceNumberList",
        "transactionReferenceNumber",
        "transactionReferenceKey",
        "commissionClaimId",
        "createdByUserId",
        "involvedUserIds",
        "supplierId",
    }
)
# Keys whose values are timestamps, however the source stored them (BSON date, ISO string, epoch number).
DATE_KEYS = frozenset(
    {
        "orderDate",
        "outForDeliveryAt",
        "deliveredAt",
        "heldAt",
        "releasedAt",
        "paymentDate",
        "createdAt",
        "reviewedAt",
        "deliveryDate",
        "invoiceDate",
        "createdDate",
        "releaseDate",
        "creationDate",
        "date",
        "closedAt",
        "postDatedCheckDate",
    }
)
# The field that names the order a document belongs to: every document of one order shares a date offset
# and an amount factor ("chain"); customers and users are chains of their own.
CHAIN_KEYS = {
    "ecommerce_payments": "salesOrderId",
    "accounting_customer_payments": "orderReferenceOfPayment",
    "salesapp_commissions": "saleReference",
}
SECONDS_PER_DAY = 86400
EPOCH_MS_THRESHOLD = 1e11


class MissingKeyError(RuntimeError):
    """`DEMO_ANON_KEY` is unset or too short: refuse to anonymise with a guessable (or no) key."""


def anon_key() -> bytes:
    key = os.environ.get(KEY_ENV, "").strip()
    if len(key) < MIN_KEY_CHARS:
        raise MissingKeyError(
            f"set {KEY_ENV} to a secret of at least {MIN_KEY_CHARS} characters "
            "(never commit it; see scripts/demo_data/README.md)"
        )
    return key.encode()


def _digest(kind: str, value: str) -> bytes:
    return hmac.new(anon_key(), f"{kind}|{value}".encode(), hashlib.sha256).digest()


def _rng(kind: str, value: str) -> random.Random:
    return random.Random(int.from_bytes(_digest(kind, value), "big"))


def date_shift() -> timedelta:
    """The secret whole number of days every timestamp moves forward by (derived from the key)."""
    span = SHIFT_DAYS_MAX - SHIFT_DAYS_MIN + 1
    return timedelta(days=SHIFT_DAYS_MIN + int.from_bytes(_digest("date-shift", ""), "big") % span)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def chain_key(collection: str, doc: Any) -> str:
    """The chain a raw document belongs to: its order's id, or its own `_id` when it has no order."""
    if not isinstance(doc, dict):
        return ""
    value = doc.get(CHAIN_KEYS.get(collection, "_id"))
    if value in (None, "", []):
        value = doc.get("_id")
    return _norm(value) if value not in (None, "") else ""


def chain_shift(chain: str) -> timedelta:
    """Forward by the secret shift, then back by the chain's own whole days and time of day."""
    rng = _rng("chain-shift", chain)
    jitter = timedelta(days=rng.randint(0, JITTER_DAYS_MAX), seconds=rng.randint(0, SECONDS_PER_DAY - 1))
    return date_shift() - jitter


def shift_datetime(value: datetime, chain: str = "") -> datetime:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware + chain_shift(chain)


def amount_factor(chain: str) -> float:
    """The factor every amount of a chain is multiplied by (0.8 to 1.2, derived from the key)."""
    spread = AMOUNT_FACTOR_MAX - AMOUNT_FACTOR_MIN
    return round(AMOUNT_FACTOR_MIN + spread * _rng("amount", chain).random(), 4)


def scale_amount(value: Any, chain: str = "") -> Any:
    """A money value scaled by its chain's factor and rounded to centavos; anything else is unchanged."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    return round(value * amount_factor(chain) + 1e-9, 2)


def looks_like_business(name: str) -> bool:
    return bool(BUSINESS_RE.search(name))


def random_person_name(rng: random.Random) -> str:
    """`First M. Surname` drawn from the generator's lists with `rng`."""
    initial = rng.choice(PERSON_INITIALS)
    return f"{rng.choice(FIRST_NAMES)} {initial}. {rng.choice(SURNAMES)}"


def random_business_name(rng: random.Random) -> str:
    """A prefix or surname plus a business type, drawn from the generator's lists with `rng`."""
    head = rng.choice(BUSINESS_PREFIXES) if rng.random() < 0.6 else rng.choice(SURNAMES)
    return f"{head} {rng.choice(BUSINESS_TYPES)}"


def random_address(rng: random.Random) -> str:
    street, barangay, city = rng.choice(STREETS), rng.choice(BARANGAYS), rng.choice(CITIES)
    return f"{rng.randint(2, 480)} {street} St., Brgy. {barangay}, {city}"


def fake_person_name(real: str) -> str:
    return random_person_name(_rng("person", _norm(real)))


def fake_business_name(real: str) -> str:
    return random_business_name(_rng("business", _norm(real)))


def fake_name(real: str) -> str:
    """A person or business name, keeping the "Person - Business" pattern when the real name has it."""
    parts = PERSON_BUSINESS_SPLIT.split(real.strip(), maxsplit=1)
    if len(parts) == 2:
        return f"{fake_person_name(parts[0])} - {fake_business_name(parts[1])}"
    return fake_business_name(real) if looks_like_business(real) else fake_person_name(real)


def is_generated_person_name(name: str) -> bool:
    """True for exactly what `fake_person_name` can produce: First M. Surname from the generator's lists."""
    first, _, rest = name.partition(" ")
    initial, dot, surname = rest.partition(" ")
    return (
        first in FIRST_NAMES
        and len(initial) == 2
        and initial[0] in PERSON_INITIALS
        and initial[1] == "."
        and bool(dot)
        and surname in SURNAMES
    )


def is_generated_business_name(name: str) -> bool:
    """True for exactly what `fake_business_name` can produce: a prefix or surname plus a business type."""
    return any(
        name == f"{head} {kind}"
        for head in (*BUSINESS_PREFIXES, *SURNAMES)
        for kind in BUSINESS_TYPES
        if name.startswith(head + " ") and name.endswith(" " + kind)
    )


def is_generated_name(name: str) -> bool:
    """True when `name` is a person, a business or a `Person - Business` pair made by this generator."""
    parts = PERSON_BUSINESS_SPLIT.split(name.strip(), maxsplit=1)
    if len(parts) == 2:
        return is_generated_person_name(parts[0]) and is_generated_business_name(parts[1])
    return is_generated_person_name(name) or is_generated_business_name(name)


def email_from_name(name: str) -> str:
    person = PERSON_BUSINESS_SPLIT.split(name.strip(), maxsplit=1)[0]
    local = re.sub(r"[^a-z0-9]+", ".", person.lower()).strip(".")
    return f"{local or 'user'}@example.com"


def fake_phone(real: str) -> str:
    digits = re.sub(r"\D", "", str(real))
    if len(digits) == 12 and digits.startswith("63"):  # +63 917 ... and 0917 ... are the same number
        digits = "0" + digits[2:]
    return f"{FICTIONAL_PHONE_PREFIX}{_rng('phone', digits).randint(0, 9999):04d}"


def fake_address(real: str) -> str:
    return random_address(_rng("address", _norm(real)))


def fake_reference(real: str, digits: int = 13) -> str:
    rng = _rng("reference", str(real))
    return "".join(str(rng.randint(0, 9)) for _ in range(digits))


_DIGITS = "0123456789"
_LOWER = "abcdefghijklmnopqrstuvwxyz"
_UPPER = _LOWER.upper()
# Whole-value shapes, tried in order: the fake id has the same length and character set as the real one.
_ID_ALPHABETS = (
    (re.compile(r"[0-9]+"), _DIGITS),
    (re.compile(r"[0-9a-f]+"), "0123456789abcdef"),
    (re.compile(r"[0-9a-z]+"), _DIGITS + _LOWER),
    (re.compile(r"[0-9A-Z]+"), _DIGITS + _UPPER),
    (re.compile(r"[0-9A-Za-z]+"), _DIGITS + _UPPER + _LOWER),
    (re.compile(r"[0-9A-Za-z_-]{20,}"), _DIGITS + _UPPER + _LOWER + "_-"),  # base64url digests, auth uids
)


def fake_id(real: Any) -> str:
    """A keyed stand-in for an id, invoice number or reference, with the same shape as the real value.

    The same real value gives the same fake one everywhere (joins survive). Punctuated values such as
    `INV-0012` keep their punctuation and swap each digit and letter for another of the same kind.
    """
    text = str(real)
    rng = _rng("id", text)
    for pattern, alphabet in _ID_ALPHABETS:
        if pattern.fullmatch(text):
            return "".join(rng.choice(alphabet) for _ in text)
    alphabets = ((_DIGITS, _DIGITS), (_LOWER, _LOWER), (_UPPER, _UPPER))
    return "".join(next((rng.choice(pool) for chars, pool in alphabets if ch in chars), ch) for ch in text)


def fake_email(real: str) -> str:
    """The fake email for a real one when nothing more is known about its owner."""
    return email_from_name(fake_person_name(real.strip().lower()))


def is_email(value: Any) -> bool:
    return isinstance(value, str) and EMAIL_RE.fullmatch(value.strip()) is not None


def scrub_text(text: str, email: Callable[[str], str] = fake_email) -> str:
    """Replace any email, phone or URL left in free text with a fake one (defence in depth)."""
    text = URL_RE.sub("[link removed]", text)
    text = EMAIL_RE.sub(lambda m: email(m.group(0)), text)
    return PHONE_RE.sub(
        lambda m: m.group(0) if FICTIONAL_PHONE_RE.fullmatch(m.group(0)) else fake_phone(m.group(0)), text
    )


Handler = Callable[["Anonymizer", Any], Any]
Shape = dict[str, Any]


class Anonymizer:
    """Stateful for the email -> name links it learns (so a user's fake email matches its fake name) and
    for the chain of the document being transformed (its date offset and amount factor)."""

    def __init__(self) -> None:
        self._name_by_email: dict[str, str] = {}
        self.chain = ""

    def learn(self, value: Any) -> None:
        """Walk raw documents and remember which real email belongs to which real display name."""
        if isinstance(value, dict):
            name = value.get("name") or value.get("displayName")
            # Some systems key users by email (`_id` == email); learn from both so the join stays consistent.
            for email in (value.get("email"), value.get("_id")):
                if is_email(email) and isinstance(name, str) and name.strip():
                    self._name_by_email.setdefault(email.strip().lower(), name)
            for child in value.values():
                self.learn(child)
        elif isinstance(value, list):
            for child in value:
                self.learn(child)

    def name(self, real: Any) -> Any:
        return fake_name(real) if isinstance(real, str) and real.strip() else real

    def person(self, real: Any) -> Any:
        return fake_person_name(real) if isinstance(real, str) and real.strip() else real

    def business(self, real: Any) -> Any:
        return fake_business_name(real) if isinstance(real, str) and real.strip() else real

    def email(self, real: Any) -> Any:
        """The fake email for a real one: derived from the owner's fake name when that owner is known."""
        if not isinstance(real, str) or not real.strip():
            return real
        known = self._name_by_email.get(real.strip().lower())
        return email_from_name(fake_name(known)) if known else fake_email(real)

    def identifier(self, value: Any) -> Any:
        """An id that is really an email (sales app user ids) becomes the matching fake email; any other
        id (or list of ids) becomes its keyed stand-in, the same one in every collection."""
        if isinstance(value, list):
            return [self.identifier(item) for item in value]
        if is_email(value):
            return self.email(value)
        return fake_id(value) if isinstance(value, str | int) and str(value).strip() else value

    def phone(self, real: Any) -> Any:
        return fake_phone(real) if isinstance(real, str | int) and str(real).strip() else real

    def address(self, real: Any) -> Any:
        return fake_address(real) if isinstance(real, str) and real.strip() else real

    def reference(self, real: Any) -> Any:
        return fake_reference(real) if isinstance(real, str | int) and str(real).strip() else real

    def date(self, value: Any) -> Any:
        """A timestamp in any stored form (BSON date, ISO string, epoch number) moved by the chain's
        offset, as an aware datetime; None stays None, and anything else that is not a timestamp becomes
        None (never copied through)."""
        if value is None:
            return None
        parsed = as_datetime(value) if isinstance(value, datetime | str | int | float | dict) else None
        return shift_datetime(parsed, self.chain) if parsed else None

    def money(self, value: Any) -> Any:
        return scale_amount(value, self.chain)

    def user(self, doc: Any) -> Any:
        """Collapse an embedded user document to `{_id, name, email}`."""
        if not isinstance(doc, dict):
            return None
        email = doc.get("email") if is_email(doc.get("email")) else doc.get("_id")
        real_name = None
        if is_email(email):
            real_name = self._name_by_email.get(email.strip().lower())
        real_name = real_name or doc.get("name") or doc.get("displayName")
        name = fake_name(real_name) if real_name else None
        fake = self.email(email) if is_email(email) else (email_from_name(name) if name else None)
        return {"_id": self.identifier(doc.get("_id")), "name": name, "email": fake}

    def unit(self, doc: Any) -> Any:
        """Keep only the product facts of an embedded unit; a supplier name becomes a fake business."""
        if not isinstance(doc, dict):
            return None
        item = doc.get("item") if isinstance(doc.get("item"), dict) else {}
        supplier = doc.get("supplier") if isinstance(doc.get("supplier"), dict) else {}
        supplier_name = doc.get("supplierName") or supplier.get("name")
        unit_id = self.identifier(doc.get("_id"))
        unit = {
            "_id": unit_id,
            # Product names and categories are free text; a keyed label keeps them distinct, nothing more.
            "name": f"Product {str(unit_id)[-6:]}" if doc.get("name") or item.get("name") else None,
            "measurementUnit": doc.get("measurementUnit") or item.get("measurementUnit"),
            # The selling price scales with the chain; the cost price (a real margin) is never exported.
            "sellingPrice": self.money(doc.get("sellingPrice", item.get("sellingPrice"))),
            "category": PRODUCT_CATEGORY if doc.get("category") else None,
        }
        if supplier_name:
            unit["supplierName"] = self.business(supplier_name)
        return unit

    def notes(self, value: Any) -> list:
        """Note lists keep their structure and (shifted) dates; the text is blanked (free text about a
        customer)."""
        if not isinstance(value, list):
            return []
        out = []
        for note in value:
            if isinstance(note, dict):
                kept = {k: self.date(note[k]) for k in ("createdDate", "date") if k in note}
                if "userName" in note:
                    kept["userName"] = self.name(note["userName"])
                kept["content"] = ""
                out.append(kept)
            elif isinstance(note, str):
                out.append("")
        return out


def keep(_anon: Anonymizer, value: Any) -> Any:
    return value


def ident(anon: Anonymizer, value: Any) -> Any:
    return anon.identifier(value)


def hold_reason(_anon: Anonymizer, value: Any) -> Any:
    return HOLD_REASON if value else value


def rejection_reason(_anon: Anonymizer, value: Any) -> Any:
    return REJECTION_REASON if value else value


def null(_anon: Anonymizer, _value: Any) -> None:
    return None


def empty_list(_anon: Anonymizer, _value: Any) -> list:
    return []


def my_business(_anon: Anonymizer, _value: Any) -> dict:
    return {"name": MY_BUSINESS["name"], "contactDetails": dict(MY_BUSINESS["contactDetails"])}


def payment_method(anon: Anonymizer, value: Any) -> Any:
    """Store orders hold `paymentMethod` as a string in some documents and as `{method, description, ...}`
    in others; only the method name survives, in the form the source used, and the description (free
    text) never does."""
    if isinstance(value, dict):
        method = value.get("method") or value.get("name")
        return {"method": scrub_text(str(method), anon.email) if method else None, "description": None}
    return scrub_text(value, anon.email) if isinstance(value, str) else None


NAME: Handler = Anonymizer.name
PERSON: Handler = Anonymizer.person
BUSINESS: Handler = Anonymizer.business
EMAIL: Handler = Anonymizer.email
PHONE: Handler = Anonymizer.phone
ADDRESS: Handler = Anonymizer.address
REFERENCE: Handler = Anonymizer.reference
USER: Handler = Anonymizer.user
UNIT: Handler = Anonymizer.unit
NOTES: Handler = Anonymizer.notes
DATE: Handler = Anonymizer.date
MONEY: Handler = Anonymizer.money
KEEP: Handler = keep
ID: Handler = ident
PAYMENT_METHOD: Handler = payment_method
HOLD_REASON_TEXT: Handler = hold_reason
REJECTION_TEXT: Handler = rejection_reason
NULL: Handler = null
EMPTY: Handler = empty_list
CONSTANT_HANDLERS = (NULL, EMPTY, my_business)

CONTACT: Shape = {
    "address": ADDRESS,
    "phone": PHONE,
    "email": EMAIL,
    "contactPerson": PERSON,
    "zipCode": NULL,
}
ACCOUNT_BALANCE: Shape = {"current": MONEY, "overdue": MONEY}
ORDER_LINE: Shape = {"quantity": KEEP, "price": MONEY, "unit": UNIT}
CREATED_BY: Shape = {"user": USER, "date": DATE}
EMBEDDED_CUSTOMER_SHAPE: Shape = {
    "_id": ID,
    "name": NAME,
    "contactDetails": CONTACT,
    "bir2303": {"tin": NULL, "registeredName": NULL},
    "paymentTerms": KEEP,
    "accountBalance": ACCOUNT_BALANCE,
    "accountManager": USER,
    "businessName": BUSINESS,
    "email": EMAIL,
    "listOfPhoneNumber": [PHONE],
}


def embedded_customer(anon: Anonymizer, value: Any) -> Any:
    """A customer embedded in an order: its balance scales by the customer's own chain (keyed on the
    customer `_id`), the same factor as the customer's own document, not by the order's."""
    if not isinstance(value, dict):
        return None
    order_chain = anon.chain
    anon.chain = chain_key("customers", value) or order_chain
    try:
        return apply_shape(anon, EMBEDDED_CUSTOMER_SHAPE, value)
    finally:
        anon.chain = order_chain


EMBEDDED_CUSTOMER: Handler = embedded_customer

SHAPES: dict[str, Shape] = {
    "ecommerce_sales_orders": {
        "_id": ID,
        "salesOrderReference": ID,
        "customerId": ID,
        "customerName": NAME,
        "customerContactName": PERSON,
        "customerBusinessName": BUSINESS,
        "contactDetails": CONTACT,
        "customerDeliveryAddress": {"addressName": ADDRESS, "latitude": NULL, "longitude": NULL},
        "itemsOrderList": [ORDER_LINE],
        "grandTotal": MONEY,
        "grandTotalWithFreight": MONEY,
        "vatTotal": MONEY,
        "netOfVat": MONEY,
        "status": KEEP,
        "paid": KEEP,
        "scannedOut": KEEP,
        "orderDate": DATE,
        "outForDeliveryAt": DATE,
        "deliveredAt": DATE,
        "invoiceNumber": ID,
        "invoiceNumberList": ID,
        "invoiceImageList": EMPTY,
        "paymentMethod": PAYMENT_METHOD,
        "paymentDocuments": EMPTY,
        "userSellerEmail": EMAIL,
        "userCreatorEmail": EMAIL,
        "closedBy": USER,
        "outForDeliveryBy": USER,
        "approvalHold": {
            "active": KEEP,
            "reason": HOLD_REASON_TEXT,
            "heldAt": DATE,
            "releasedAt": DATE,
            "heldBy": USER,
        },
        "feedbackToken": NULL,
        "createdBy": CREATED_BY,
    },
    "ecommerce_payments": {
        "_id": ID,
        "salesOrderId": ID,
        "customerId": ID,
        "amount": MONEY,
        "modeOfPayment": KEEP,
        "screenshotUrl": NULL,
        "transactionReferenceNumber": REFERENCE,
        "transactionReferenceKey": REFERENCE,
        "paymentDate": DATE,
        "status": KEEP,
        "createdAt": DATE,
        "createdByUserId": ID,
        "createdByUserEmail": EMAIL,
        "reviewedByUserEmail": EMAIL,
        "reviewedAt": DATE,
        "rejectionReason": REJECTION_TEXT,
        "accountingPaymentResult": {"paid": KEEP, "balance": MONEY},
    },
    "ecommerce_customers": {
        "_id": ID,
        "name": NAME,
        "customerName": NAME,
        "businessName": BUSINESS,
        "contactName": PERSON,
        "contactPerson": PERSON,
        "email": EMAIL,
        "phone": PHONE,
        "contactDetails": CONTACT,
        "deliveryAddress": {"addressName": ADDRESS, "latitude": NULL, "longitude": NULL},
        "deliveryAddressList": [{"addressName": ADDRESS, "latitude": NULL, "longitude": NULL}],
        "paymentTerms": KEEP,
        "accountingCustomerId": ID,
        "createdBy": CREATED_BY,
    },
    "ecommerce_users": {
        "_id": ID,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "accounting_sales_orders": {
        "_id": ID,
        "myBusiness": my_business,
        "customer": EMBEDDED_CUSTOMER,
        "itemsOrderList": [ORDER_LINE],
        "grandTotal": MONEY,
        "netOfVat": MONEY,
        "vatTotal": MONEY,
        "amountToReceive": MONEY,
        "balance": MONEY,
        "totalPaymentReceived": MONEY,
        "paid": KEEP,
        "delivered": KEEP,
        "deliveryDate": DATE,
        "invoiceNumber": ID,
        "invoiceDate": DATE,
        "invoiceImageList": EMPTY,
        "isFromEcommerce": KEEP,
        "type": KEEP,
        "createdBy": CREATED_BY,
    },
    "accounting_customers": {
        "_id": ID,
        "name": NAME,
        "contactDetails": CONTACT,
        "bir2303": {"tin": NULL, "registeredName": NULL, "photoOfBir2303orCOR": NULL},
        "paymentTerms": KEEP,
        "accountBalance": ACCOUNT_BALANCE,
        "notesList": NOTES,
        "accountManager": USER,
        "creditLimit": NULL,
        "businessName": BUSINESS,
        "createdBy": CREATED_BY,
    },
    "accounting_customer_payments": {
        "_id": ID,
        "amount": MONEY,
        "imageProofsList": EMPTY,
        "paymentMethod": {"method": KEEP, "description": NULL},
        "isPostDatedCheck": KEEP,
        "postDatedCheckDate": DATE,
        "orderReferenceOfPayment": ID,
        "customer": {"_id": ID, "name": NAME},
        "createdBy": CREATED_BY,
    },
    "accounting_users": {
        "_id": ID,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "warehouse_served_orders": {
        "_id": ID,
        "customerName": NAME,
        "createdByUserName": NAME,
        "createdDate": DATE,
        "released": KEEP,
        "releaseDate": DATE,
        "deliveryDate": DATE,
        "itemsOrderList": [{"quantity": KEEP, "unit": UNIT}],
        "deliveryList": [{"_id": ID, "creationDate": DATE, "delivered": KEEP, "deliveryDate": DATE}],
        "notesList": NOTES,
    },
    "salesapp_sales": {
        "_id": ID,
        "userSeller": USER,
        "userCreator": USER,
        "customer": EMBEDDED_CUSTOMER,
        "date": DATE,
        "paid": KEEP,
        "delivered": KEEP,
        "closed": KEEP,
        "closedAt": DATE,
        "totalSale": MONEY,
        "orderList": [ORDER_LINE],
        "involvedUserIds": ID,
    },
    "salesapp_commissions": {
        "_id": ID,
        "type": KEEP,
        "saleReference": ID,
        "user": USER,
        "percentToSeller": KEEP,
        "percentToCreator": KEEP,
        "commissionsEarned": MONEY,
        "commissionClaimed": KEEP,
        "commissionClaimId": ID,
        "createdDate": DATE,
        "pointsEarned": NULL,  # a real loyalty tally; the demo never reads it
    },
    "salesapp_users": {
        "_id": ID,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "salesapp_customers": {
        "_id": ID,
        "name": NAME,
        "email": EMAIL,
        "listOfPhoneNumber": [PHONE],
        "accountBalance": ACCOUNT_BALANCE,
        "accountManager": USER,
    },
}


def projection(collection: str) -> dict[str, int]:
    """The MongoDB projection that fetches exactly the fields a collection's SHAPE keeps."""

    def paths(shape: Any, prefix: str) -> list[str]:
        if isinstance(shape, dict):
            return [p for key, child in shape.items() for p in paths(child, f"{prefix}{key}.")]
        if isinstance(shape, list):
            return paths(shape[0], prefix)
        if shape is UNIT:
            return [
                f"{prefix}{f}"
                for f in (
                    "_id",
                    "name",
                    "measurementUnit",
                    "sellingPrice",
                    "category",
                    "supplierName",
                    "supplier.name",
                    "item.name",
                    "item.measurementUnit",
                    "item.sellingPrice",
                )  # fmt: skip
            ]
        if shape is USER:
            return [f"{prefix}{f}" for f in ("_id", "name", "displayName", "email")]
        if shape is EMBEDDED_CUSTOMER:
            return paths(EMBEDDED_CUSTOMER_SHAPE, prefix)
        if shape is NOTES:
            return [f"{prefix}{f}" for f in ("createdDate", "date", "userName", "content")]
        if shape in CONSTANT_HANDLERS:
            return []
        return [prefix.rstrip(".")]

    return {path: 1 for path in paths(SHAPES[collection], "") if path}


def apply_shape(anon: Anonymizer, shape: Any, value: Any, key: str | None = None) -> Any:
    """Trim `value` to `shape`; KEEP leaves are scrubbed, every other handler already yields fake data."""
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return None
        return {
            k: apply_shape(anon, child, value.get(k), k)
            for k, child in shape.items()
            if k in value or child in CONSTANT_HANDLERS
        }
    if isinstance(shape, list):
        if not isinstance(value, list):
            return []
        return [apply_shape(anon, shape[0], item, key) for item in value]
    if shape is KEEP:
        return scrub(anon, value, key)
    return shape(anon, value)


def scrub_key(anon: Anonymizer, key: Any) -> Any:
    """A dict key: an email key becomes its fake (join keys); any other key is scrubbed like free text."""
    if is_email(key):
        return anon.email(key)
    return scrub_text(key, anon.email) if isinstance(key, str) else key


def scrub(anon: Anonymizer, value: Any, key: str | None = None) -> Any:
    """Deep pass over a kept value (defence in depth).

    A string that is exactly an email, wherever it sits (an `_id`, an `...Ids` list, a dict key), becomes
    that email's consistent fake so joins survive; other identifier fields get their keyed stand-in; every
    other string is scrubbed for leftover emails, phones and URLs; every datetime, and every string or
    number under a date key, moves by the chain's offset.
    """
    if isinstance(value, dict):
        return {scrub_key(anon, k): scrub(anon, v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(anon, v, key) for v in value]
    if isinstance(value, datetime) or (key in DATE_KEYS and isinstance(value, str | int | float)):
        return anon.date(value)
    if is_email(value):
        return anon.email(value)
    if isinstance(value, str) and key in ID_KEYS:
        return fake_id(value)
    if isinstance(value, str):
        return scrub_text(value, anon.email)
    return value


def transform(anon: Anonymizer, collection: str, doc: dict) -> dict:
    """Trim a raw source document to its SHAPE and anonymise it within its chain."""
    anon.chain = chain_key(collection, doc)
    return apply_shape(anon, SHAPES[collection], doc)


def transform_all(anon: Anonymizer, data: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Anonymise every collection after learning the email/name links across all of them."""
    anon.learn(data)
    return {name: [transform(anon, name, doc) for doc in docs] for name, docs in data.items()}


def as_datetime(value: Any) -> datetime | None:
    """A BSON date, Extended JSON `{"$date": ...}` or ISO string as an aware UTC datetime."""
    if isinstance(value, dict) and "$date" in value:
        value = value["$date"]
        if isinstance(value, dict) and "$numberLong" in value:
            value = int(value["$numberLong"])
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):  # epoch milliseconds (BSON) or seconds (anything before 1973 is ms)
        return datetime.fromtimestamp(value / 1000 if abs(value) >= EPOCH_MS_THRESHOLD else value, tz=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def iso_z(value: Any) -> str | None:
    """ISO-8601 UTC with second precision and a `Z` suffix, as the connector contract wants."""
    parsed = as_datetime(value)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if parsed else None


def jsonable(value: Any) -> Any:
    """Plain JSON with datetimes as Extended JSON `{"$date": ...}` (what the out/ files hold)."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=UTC)
        return {
            "$date": aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{aware.microsecond // 1000:03d}Z"
        }
    return value


def from_jsonable(value: Any) -> Any:
    """The inverse of `jsonable`: `{"$date": ...}` back to aware datetimes."""
    if isinstance(value, dict):
        if set(value) == {"$date"}:
            return as_datetime(value)
        return {k: from_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_jsonable(v) for v in value]
    return value
