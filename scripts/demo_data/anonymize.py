"""Deterministic anonymiser for the Order-to-Cash demo dataset (pure functions, no database).

Every fake value is derived from a SHA-256 of the real value, so the same real customer, user, phone or
address becomes the same fake one in all four source systems and the joins (`_id`, order references,
customer ids) survive untouched. Each collection has a SHAPE below that lists the fields kept from the
source document and the handler applied to each; everything not listed is dropped, which is how the
giant embedded unit documents, images, signatures and roles never reach the export. A final pass scrubs
any string that still looks like an email, phone number or URL.
"""

import hashlib
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

NAMESPACE = "new-machines-o2c-demo-v1"
MY_BUSINESS = {
    "name": "Northline Packaging Co.",
    "contactDetails": {
        "address": "Lot 14 Cabancalan Industrial Rd., Brgy. Cabancalan, Mandaue City",
        "phone": "0917 555 0142",
        "email": "orders@northline-packaging.example.com",
    },
}

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
    "Ong", "Sy", "Go", "Chua", "Dimaculangan", "Bacalso", "Cañete", "Montecillo", "Pepito", "Suico",
]  # fmt: skip
BUSINESS_PREFIXES = [
    "Sunrise", "Golden", "Island", "Harbor", "Mabuhay", "Lakeside", "Starlight", "Cebuano", "Northgate",
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
STREETS = [
    "Mabini", "Rizal", "Bonifacio", "Osmena", "Magallanes", "Colon", "Jakosalem", "Lapu-Lapu",
    "Katipunan", "Aguinaldo", "Luna", "Burgos", "Del Pilar", "Escario", "Gorordo", "Sampaguita",
    "Banawa", "Juana Osmena", "Salinas", "Pelaez",
]  # fmt: skip
BARANGAYS = [
    "Lahug", "Mabolo", "Talamban", "Guadalupe", "Banilad", "Capitol Site", "Tisa", "Labangon", "Pardo",
    "Basak", "Poblacion", "San Antonio", "Sta. Cruz", "Bagong Silang", "Malate", "Ermita", "Pasong Tamo",
    "Kamuning", "Tejeros", "Apas", "Kasambagan", "Subangdaku",
]  # fmt: skip
CITIES = [
    "Cebu City", "Mandaue City", "Lapu-Lapu City", "Talisay City", "Makati City", "Quezon City",
    "Pasig City", "Manila", "Consolacion", "Minglanilla",
]  # fmt: skip
MOBILE_PREFIXES = [
    "17", "18", "19", "20", "21", "27", "28", "29", "36", "38", "39", "45", "46", "47", "48", "49", "50",
    "55", "56", "61", "63", "65", "66", "67", "77", "78", "79", "94", "95", "96", "97", "98", "99",
]  # fmt: skip

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


def _rng(kind: str, value: str) -> random.Random:
    digest = hashlib.sha256(f"{NAMESPACE}|{kind}|{value}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def looks_like_business(name: str) -> bool:
    return bool(BUSINESS_RE.search(name))


def fake_person_name(real: str) -> str:
    rng = _rng("person", _norm(real))
    initial = rng.choice("ABCDEFGHJKLMNOPRSTV")
    return f"{rng.choice(FIRST_NAMES)} {initial}. {rng.choice(SURNAMES)}"


def fake_business_name(real: str) -> str:
    rng = _rng("business", _norm(real))
    head = rng.choice(BUSINESS_PREFIXES) if rng.random() < 0.6 else rng.choice(SURNAMES)
    return f"{head} {rng.choice(BUSINESS_TYPES)}"


def fake_name(real: str) -> str:
    """A person or business name, keeping the "Person - Business" pattern when the real name has it."""
    parts = PERSON_BUSINESS_SPLIT.split(real.strip(), maxsplit=1)
    if len(parts) == 2:
        return f"{fake_person_name(parts[0])} - {fake_business_name(parts[1])}"
    return fake_business_name(real) if looks_like_business(real) else fake_person_name(real)


def email_from_name(name: str) -> str:
    person = PERSON_BUSINESS_SPLIT.split(name.strip(), maxsplit=1)[0]
    local = re.sub(r"[^a-z0-9]+", ".", person.lower()).strip(".")
    return f"{local or 'user'}@example.com"


def fake_phone(real: str) -> str:
    digits = re.sub(r"\D", "", str(real))
    if len(digits) == 12 and digits.startswith("63"):  # +63 917 ... and 0917 ... are the same number
        digits = "0" + digits[2:]
    rng = _rng("phone", digits)
    return f"09{rng.choice(MOBILE_PREFIXES)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


def fake_address(real: str) -> str:
    rng = _rng("address", _norm(real))
    street, barangay, city = rng.choice(STREETS), rng.choice(BARANGAYS), rng.choice(CITIES)
    return f"{rng.randint(2, 480)} {street} St., Brgy. {barangay}, {city}"


def fake_reference(real: str, digits: int = 13) -> str:
    rng = _rng("reference", str(real))
    return "".join(str(rng.randint(0, 9)) for _ in range(digits))


def fake_email(real: str) -> str:
    """The fake email for a real one when nothing more is known about its owner."""
    return email_from_name(fake_person_name(real.strip().lower()))


def is_email(value: Any) -> bool:
    return isinstance(value, str) and EMAIL_RE.fullmatch(value.strip()) is not None


def scrub_text(text: str, email: Callable[[str], str] = fake_email) -> str:
    """Replace any email, phone or URL left in free text with a fake one (defence in depth)."""
    text = URL_RE.sub("[link removed]", text)
    text = EMAIL_RE.sub(lambda m: email(m.group(0)), text)
    return PHONE_RE.sub(lambda m: fake_phone(m.group(0)), text)


Handler = Callable[["Anonymizer", Any], Any]
Shape = dict[str, Any]


class Anonymizer:
    """Stateful only for the email -> name links it learns, so a user's fake email matches its fake name."""

    def __init__(self) -> None:
        self._name_by_email: dict[str, str] = {}

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
        """An id that is really an email (sales app user ids) becomes the matching fake email."""
        return self.email(value) if is_email(value) else value

    def phone(self, real: Any) -> Any:
        return fake_phone(real) if isinstance(real, str | int) and str(real).strip() else real

    def address(self, real: Any) -> Any:
        return fake_address(real) if isinstance(real, str) and real.strip() else real

    def reference(self, real: Any) -> Any:
        return fake_reference(real) if isinstance(real, str | int) and str(real).strip() else real

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
        unit = {
            "_id": doc.get("_id"),
            "name": doc.get("name") or item.get("name"),
            "measurementUnit": doc.get("measurementUnit") or item.get("measurementUnit"),
            "sellingPrice": doc.get("sellingPrice", item.get("sellingPrice")),
            "costPrice": doc.get("costPrice", item.get("costPrice")),
            "category": doc.get("category"),
        }
        if supplier_name:
            unit["supplierName"] = self.business(supplier_name)
        return unit

    def notes(self, value: Any) -> list:
        """Note lists keep their structure and dates; the text is blanked (free text about a customer)."""
        if not isinstance(value, list):
            return []
        out = []
        for note in value:
            if isinstance(note, dict):
                kept = {k: note[k] for k in ("createdDate", "date") if k in note}
                if "userName" in note:
                    kept["userName"] = self.name(note["userName"])
                kept["content"] = ""
                out.append(kept)
            elif isinstance(note, str):
                out.append("")
        return out


def keep(_anon: Anonymizer, value: Any) -> Any:
    return value


def null(_anon: Anonymizer, _value: Any) -> None:
    return None


def empty_list(_anon: Anonymizer, _value: Any) -> list:
    return []


def my_business(_anon: Anonymizer, _value: Any) -> dict:
    return {"name": MY_BUSINESS["name"], "contactDetails": dict(MY_BUSINESS["contactDetails"])}


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
KEEP: Handler = keep
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
ACCOUNT_BALANCE: Shape = {"current": KEEP, "overdue": KEEP}
ORDER_LINE: Shape = {"quantity": KEEP, "price": KEEP, "unit": UNIT}
CREATED_BY: Shape = {"user": USER, "date": KEEP}
EMBEDDED_CUSTOMER: Shape = {
    "_id": KEEP,
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

SHAPES: dict[str, Shape] = {
    "ecommerce_sales_orders": {
        "_id": KEEP,
        "salesOrderReference": KEEP,
        "customerId": KEEP,
        "customerName": NAME,
        "customerContactName": PERSON,
        "customerBusinessName": BUSINESS,
        "contactDetails": CONTACT,
        "customerDeliveryAddress": {"addressName": ADDRESS, "latitude": NULL, "longitude": NULL},
        "itemsOrderList": [ORDER_LINE],
        "grandTotal": KEEP,
        "grandTotalWithFreight": KEEP,
        "vatTotal": KEEP,
        "netOfVat": KEEP,
        "status": KEEP,
        "paid": KEEP,
        "scannedOut": KEEP,
        "orderDate": KEEP,
        "outForDeliveryAt": KEEP,
        "deliveredAt": KEEP,
        "invoiceNumber": KEEP,
        "invoiceNumberList": KEEP,
        "invoiceImageList": EMPTY,
        "paymentMethod": KEEP,
        "paymentDocuments": EMPTY,
        "userSellerEmail": EMAIL,
        "userCreatorEmail": EMAIL,
        "closedBy": USER,
        "outForDeliveryBy": USER,
        "approvalHold": {"active": KEEP, "reason": KEEP, "heldAt": KEEP, "releasedAt": KEEP, "heldBy": USER},
        "feedbackToken": NULL,
        "createdBy": CREATED_BY,
    },
    "ecommerce_payments": {
        "_id": KEEP,
        "salesOrderId": KEEP,
        "customerId": KEEP,
        "amount": KEEP,
        "modeOfPayment": KEEP,
        "screenshotUrl": NULL,
        "transactionReferenceNumber": REFERENCE,
        "transactionReferenceKey": REFERENCE,
        "paymentDate": KEEP,
        "status": KEEP,
        "createdAt": KEEP,
        "createdByUserId": KEEP,
        "createdByUserEmail": EMAIL,
        "reviewedByUserEmail": EMAIL,
        "reviewedAt": KEEP,
        "rejectionReason": KEEP,
        "accountingPaymentResult": {"paid": KEEP, "balance": KEEP},
    },
    "ecommerce_customers": {
        "_id": KEEP,
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
        "accountingCustomerId": KEEP,
        "createdBy": CREATED_BY,
    },
    "ecommerce_users": {
        "_id": KEEP,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "accounting_sales_orders": {
        "_id": KEEP,
        "myBusiness": my_business,
        "customer": EMBEDDED_CUSTOMER,
        "itemsOrderList": [ORDER_LINE],
        "grandTotal": KEEP,
        "netOfVat": KEEP,
        "vatTotal": KEEP,
        "amountToReceive": KEEP,
        "balance": KEEP,
        "totalPaymentReceived": KEEP,
        "paid": KEEP,
        "delivered": KEEP,
        "deliveryDate": KEEP,
        "invoiceNumber": KEEP,
        "invoiceDate": KEEP,
        "invoiceImageList": EMPTY,
        "isFromEcommerce": KEEP,
        "type": KEEP,
        "createdBy": CREATED_BY,
    },
    "accounting_customers": {
        "_id": KEEP,
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
        "_id": KEEP,
        "amount": KEEP,
        "imageProofsList": EMPTY,
        "paymentMethod": {"method": KEEP, "description": KEEP},
        "isPostDatedCheck": KEEP,
        "postDatedCheckDate": KEEP,
        "orderReferenceOfPayment": KEEP,
        "customer": {"_id": KEEP, "name": NAME},
        "createdBy": CREATED_BY,
    },
    "accounting_users": {
        "_id": KEEP,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "warehouse_served_orders": {
        "_id": KEEP,
        "customerName": NAME,
        "createdByUserName": NAME,
        "createdDate": KEEP,
        "released": KEEP,
        "releaseDate": KEEP,
        "deliveryDate": KEEP,
        "itemsOrderList": [{"quantity": KEEP, "unit": UNIT}],
        "deliveryList": [{"_id": KEEP, "creationDate": KEEP, "delivered": KEEP, "deliveryDate": KEEP}],
        "notesList": NOTES,
    },
    "salesapp_sales": {
        "_id": KEEP,
        "userSeller": USER,
        "userCreator": USER,
        "customer": EMBEDDED_CUSTOMER,
        "date": KEEP,
        "paid": KEEP,
        "delivered": KEEP,
        "closed": KEEP,
        "closedAt": KEEP,
        "totalSale": KEEP,
        "orderList": [ORDER_LINE],
        "involvedUserIds": KEEP,
    },
    "salesapp_commissions": {
        "_id": KEEP,
        "type": KEEP,
        "saleReference": KEEP,
        "user": USER,
        "percentToSeller": KEEP,
        "percentToCreator": KEEP,
        "commissionsEarned": KEEP,
        "commissionClaimed": KEEP,
        "commissionClaimId": KEEP,
        "createdDate": KEEP,
        "pointsEarned": KEEP,
    },
    "salesapp_users": {
        "_id": KEEP,
        "name": NAME,
        "displayName": NAME,
        "email": EMAIL,
        "roles": KEEP,
        "userType": KEEP,
    },
    "salesapp_customers": {
        "_id": KEEP,
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
                    "costPrice",
                    "category",
                    "supplierName",
                    "supplier.name",
                    "item.name",
                    "item.measurementUnit",
                    "item.sellingPrice",
                    "item.costPrice",
                )  # fmt: skip
            ]
        if shape is USER:
            return [f"{prefix}{f}" for f in ("_id", "name", "displayName", "email")]
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


def scrub(anon: Anonymizer, value: Any, key: str | None = None) -> Any:
    """Deep pass over a kept value (defence in depth).

    A string that is exactly an email, wherever it sits (an `_id`, an `...Ids` list, a dict key), becomes
    that email's consistent fake so joins survive; other identifier fields are left alone; every other
    string is scrubbed for leftover emails, phones and URLs.
    """
    if isinstance(value, dict):
        return {scrub(anon, k, "_id"): scrub(anon, v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(anon, v, key) for v in value]
    if is_email(value):
        return anon.email(value)
    if isinstance(value, str) and key not in ID_KEYS:
        return scrub_text(value, anon.email)
    return value


def transform(anon: Anonymizer, collection: str, doc: dict) -> dict:
    """Trim a raw source document to its SHAPE and anonymise it."""
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
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
