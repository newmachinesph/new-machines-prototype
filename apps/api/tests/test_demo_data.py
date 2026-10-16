"""scripts/demo_data: the anonymiser is deterministic and leaks nothing, the planted cases agree across the
four systems, and the generated sandbox fixtures follow the connector contract. No database, no pymongo."""

import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

DEMO_DATA = Path(__file__).parents[3] / "scripts" / "demo_data"
sys.path.insert(0, str(DEMO_DATA))

import anonymize  # noqa: E402
import check_leaks  # noqa: E402
import fixtures  # noqa: E402
import plant  # noqa: E402

AS_OF = datetime(2026, 10, 16, 8, tzinfo=UTC)
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REAL_EMAIL = "juan.delacruz@gmail.com"
REAL_PHONE = "+63 917 123 4567"
REAL_URL = "https://firebasestorage.googleapis.com/v0/b/app/o/invoice.jpg"
# Each fixture file, the key its tool returns and the exact field set of every row (the connector contract).
CONTRACT = {
    "ecommerce/list_orders.json": (
        "orders",
        {"id", "reference", "customer_id", "customer_name", "order_date", "status", "paid", "scanned_out",
         "out_for_delivery_at", "delivered_at", "grand_total", "currency", "seller_email", "payment_method"},
    ),
    "ecommerce/list_payments.json": (
        "payments",
        {"id", "order_id", "customer_id", "amount", "currency", "mode_of_payment", "status", "payment_date",
         "created_at", "reference"},
    ),
    "accounting/list_sales_orders.json": (
        "sales_orders",
        {"id", "invoice_number", "invoice_date", "customer_id", "customer_name", "payment_terms_days",
         "account_manager", "account_manager_email", "grand_total", "total_payment_received", "balance",
         "currency", "paid", "delivered", "delivery_date", "is_from_ecommerce", "created_at"},
    ),
    "accounting/list_customers.json": (
        "customers",
        {"id", "name", "email", "phone", "payment_terms_days", "balance_current", "balance_overdue",
         "account_manager", "account_manager_email", "notes"},
    ),
    "accounting/list_customer_payments.json": (
        "payments",
        {"id", "order_id", "customer_id", "amount", "currency", "method", "date"},
    ),
    "warehouse/list_served_orders.json": (
        "served_orders",
        {"id", "customer_name", "created_at", "released", "release_date", "delivered", "delivered_at",
         "delivery_count", "notes"},
    ),
    "salesapp/list_sales.json": (
        "sales",
        {"id", "seller_name", "seller_email", "customer_id", "customer_name", "date", "total", "currency",
         "paid", "delivered", "closed"},
    ),
}  # fmt: skip


def sample_order() -> dict:
    """A raw ecommerce order the way the source database shapes it, full of real-looking contact data."""
    when = datetime(2026, 10, 1, 2, 30, tzinfo=UTC)
    user = {
        "_id": "u9",
        "displayName": "Maria Santos",
        "email": "maria.santos@company.ph",
        "roles": ["admin"],
    }
    return {
        "_id": "SO-123",
        "salesOrderReference": "SO-2026-00123",
        "customerId": "c1",
        "customerName": "Juan Dela Cruz - JDC Sari-Sari Store",
        "customerContactName": "Juan Dela Cruz",
        "customerBusinessName": "JDC Sari-Sari Store",
        "contactDetails": {"phone": REAL_PHONE, "contactPerson": "Juan Dela Cruz", "email": REAL_EMAIL},
        "customerDeliveryAddress": {"addressName": "123 Real St, Cebu", "latitude": 10.3, "longitude": 123.9},
        "itemsOrderList": [
            {
                "quantity": 3,
                "unit": {
                    "_id": "u1",
                    "name": "Paper Cup",
                    "measurementUnit": "pc",
                    "sellingPrice": 2.4,
                    "category": "Cups",
                    "image": REAL_URL,
                    "customerOrdersAndQuantity": {"Juan Dela Cruz": 3},
                },
            }
        ],
        "grandTotal": 7.2,
        "status": "delivered",
        "paid": True,
        "orderDate": when,
        "invoiceNumber": "INV-9981",
        "invoiceImageList": [REAL_URL],
        "paymentDocuments": [REAL_URL],
        "userSellerEmail": "maria.santos@company.ph",
        "closedBy": {**user, "signature": REAL_URL},
        "feedbackToken": "secret-token",
        "approvalHold": {"active": False, "reason": f"call {REAL_PHONE} or email {REAL_EMAIL}"},
        "createdBy": {"user": user, "date": when},
    }


def test_fake_names_are_deterministic_and_distinct():
    assert anonymize.fake_name("Juan Dela Cruz") == anonymize.fake_name("juan dela  cruz ")
    assert anonymize.fake_name("Juan Dela Cruz") != anonymize.fake_name("Pedro Penduko")
    assert anonymize.fake_phone("0917 123 4567") == anonymize.fake_phone("+63 917-123-4567")
    assert (
        anonymize.fake_reference("ABC") == anonymize.fake_reference("ABC") != anonymize.fake_reference("ABD")
    )
    assert re.fullmatch(r"\d{13}", anonymize.fake_reference("ABC"))


def test_business_names_and_person_business_pattern():
    assert anonymize.looks_like_business("JDC Sari-Sari Store")
    assert anonymize.looks_like_business("Bayview Catering")
    assert not anonymize.looks_like_business("Juan Dela Cruz")
    combined = anonymize.fake_name("Juan Dela Cruz - JDC Sari-Sari Store")
    person, business = combined.split(" - ")
    assert person == anonymize.fake_person_name("Juan Dela Cruz")
    assert business == anonymize.fake_business_name("JDC Sari-Sari Store")
    assert anonymize.fake_name("Juan Dela Cruz") == person


def test_sample_order_keeps_no_real_contact_data():
    raw = sample_order()
    anon = anonymize.Anonymizer()
    anon.learn(raw)
    out = anonymize.transform(anon, "ecommerce_sales_orders", raw)
    text = json.dumps(anonymize.jsonable(out))
    leaks = (REAL_EMAIL, "gmail", "company.ph", "917 123 4567", "9171234567", "http", "firebase", "Juan",
             "Dela Cruz", "JDC", "Maria Santos", "secret-token", "Real St", "signature", "roles")  # fmt: skip
    for leak in leaks:
        assert leak not in text, leak
    assert all(email.endswith("@example.com") for email in anonymize.EMAIL_RE.findall(text))
    assert re.fullmatch(r"09\d{2} \d{3} \d{4}", out["contactDetails"]["phone"])
    # Joins and business facts survive untouched.
    assert out["_id"] == "SO-123" and out["salesOrderReference"] == "SO-2026-00123"
    assert out["customerId"] == "c1" and out["invoiceNumber"] == "INV-9981" and out["grandTotal"] == 7.2
    assert out["orderDate"] == raw["orderDate"] and out["status"] == "delivered" and out["paid"] is True
    assert out["customerDeliveryAddress"]["latitude"] is None and out["feedbackToken"] is None
    assert out["invoiceImageList"] == [] and out["paymentDocuments"] == []
    assert out["itemsOrderList"][0]["unit"] == {
        "_id": "u1", "name": "Paper Cup", "measurementUnit": "pc", "sellingPrice": 2.4, "costPrice": None,
        "category": "Cups",
    }  # fmt: skip
    # The embedded user collapses to {_id, name, email} and its fake email matches its fake name.
    assert set(out["closedBy"]) == {"_id", "name", "email"}
    assert out["closedBy"]["email"] == anonymize.email_from_name(out["closedBy"]["name"])
    assert out["userSellerEmail"] == out["closedBy"]["email"] == out["createdBy"]["user"]["email"]
    assert out["customerContactName"] == out["customerName"].split(" - ")[0]


def test_accounting_order_trims_units_and_replaces_my_business():
    raw = {
        "_id": "SO-1",
        "myBusiness": {"name": "Real Business Inc", "companyLogoUrl": REAL_URL, "bir2303": {"tin": "1"}},
        "customer": {
            "_id": "c1",
            "name": "JDC Sari-Sari Store",
            "contactDetails": {
                "address": "1 Real St",
                "phone": "09171234567",
                "email": REAL_EMAIL,
                "zipCode": "6000",
            },
            "bir2303": {
                "tin": "123-456-789",
                "registeredName": "JUAN DELA CRUZ",
                "photoOfBir2303orCOR": REAL_URL,
            },
            "paymentTerms": 30,
            "accountBalance": {"current": 100.0, "overdue": 40.0},
            "accountManager": {
                "_id": "m1",
                "displayName": "Ana Reyes",
                "email": "ana@company.ph",
                "roles": ["x"],
            },
        },
        "itemsOrderList": [
            {
                "quantity": 2,
                "price": 5.0,
                "unit": {
                    "_id": "u2",
                    "item": {"name": "Box", "costPrice": 1.0, "sellingPrice": 5.0, "measurementUnit": "pc"},
                    "supplier": {"name": "Big Supplier Corp", "contactDetails": {"phone": "0917 999 8888"}},
                    "approverUsers": [{"name": "Someone", "email": "someone@company.ph"}],
                    "outOfStockDays90": [1, 2, 3],
                },
            }
        ],
        "grandTotal": 10.0,
        "balance": 10.0,
        "paid": False,
        "delivered": True,
        "invoiceNumber": "7781",
        "createdBy": {
            "user": {"_id": "m1", "email": "ana@company.ph"},
            "date": datetime(2026, 10, 2, tzinfo=UTC),
        },
    }
    anon = anonymize.Anonymizer()
    anon.learn(raw)
    out = anonymize.transform(anon, "accounting_sales_orders", raw)
    text = json.dumps(anonymize.jsonable(out))
    for leak in ("Real Business", "http", "123-456", "JUAN", "6000", "company.ph", "gmail", "Big Supplier",
                 "approverUsers", "outOfStockDays90", "Someone", "Ana Reyes", "roles"):  # fmt: skip
        assert leak not in text, leak
    assert out["myBusiness"]["name"] == "Northline Packaging Co."
    assert out["customer"]["bir2303"] == {"tin": None, "registeredName": None}
    assert out["customer"]["contactDetails"]["zipCode"] is None
    assert out["customer"]["accountBalance"] == {"current": 100.0, "overdue": 40.0}
    assert out["customer"]["accountManager"]["email"] == out["createdBy"]["user"]["email"]
    unit = out["itemsOrderList"][0]["unit"]
    assert unit["name"] == "Box" and unit["costPrice"] == 1.0 and "supplierName" in unit
    assert out["balance"] == 10.0 and out["invoiceNumber"] == "7781"


def test_projection_never_fetches_dropped_blobs():
    for collection in anonymize.SHAPES:
        paths = anonymize.projection(collection)
        assert paths, collection
        assert all(v == 1 for v in paths.values())
        assert not any(
            part in path
            for path in paths
            for part in (
                "image",
                "Url",
                "approverUsers",
                "outOfStockDays90",
                "customerOrders",
                "myBusiness",
            )
        ), collection


def test_scrub_text_catches_leftovers():
    scrubbed = anonymize.scrub_text(f"ping {REAL_EMAIL} at {REAL_PHONE}, (032) 233 4455 or {REAL_URL}")
    assert "gmail" not in scrubbed and "123 4567" not in scrubbed and "233 4455" not in scrubbed
    assert "http" not in scrubbed and "@example.com" in scrubbed
    assert anonymize.scrub_text("INV-20261001 for 2026-10-01") == "INV-20261001 for 2026-10-01"


def test_emails_used_as_ids_become_consistent_fake_join_keys():
    """The sales app keys users by email: Users._id, userSeller._id, involvedUserIds, Commissions.user._id."""
    seller = {
        "_id": "nikka@realcompany.ph",
        "name": "Nikka Real",
        "email": "nikka@realcompany.ph",
        "roles": ["x"],
    }
    creator = {"_id": "ben@realcompany.ph", "name": "Ben Real", "email": "ben@realcompany.ph"}
    raw = {
        "salesapp_users": [seller, creator],
        "salesapp_sales": [
            {
                "_id": "S-1",
                "userSeller": seller,
                "userCreator": {"_id": "ben@realcompany.ph", "displayName": "Ben R. Real"},
                "customer": {"_id": "c1", "name": "Juan Dela Cruz", "email": REAL_EMAIL},
                "paid": False,
                "involvedUserIds": ["nikka@realcompany.ph", "ben@realcompany.ph", "u-plain-id"],
            }
        ],
        "salesapp_commissions": [
            {
                "_id": "COM-1",
                "saleReference": "S-1",
                "user": {"_id": "nikka@realcompany.ph"},
                "commissionClaimed": False,
            }
        ],
        "ecommerce_payments": [
            {"_id": "P-1", "salesOrderId": "S-1", "createdByUserId": "nikka@realcompany.ph", "amount": 1.0}
        ],
        "accounting_sales_orders": [
            {
                "_id": "S-1",
                "createdBy": {"user": {"_id": "ben@realcompany.ph"}, "date": AS_OF},
                "grandTotal": 1.0,
            }
        ],
    }
    out = anonymize.transform_all(anonymize.Anonymizer(), raw)
    text = json.dumps(anonymize.jsonable(out))
    assert "realcompany" not in text and "gmail" not in text and "Nikka" not in text and "Ben" not in text
    assert not check_leaks.scan_value(json.loads(text))
    users = {u["_id"]: u for u in out["salesapp_users"]}
    sale = out["salesapp_sales"][0]
    assert sale["userSeller"]["_id"] in users and sale["userCreator"]["_id"] in users
    assert (
        sale["userSeller"]["_id"] == sale["userSeller"]["email"] == users[sale["userSeller"]["_id"]]["email"]
    )
    assert users[sale["userSeller"]["_id"]]["name"] == sale["userSeller"]["name"]
    assert sale["userCreator"]["_id"] == users[sale["userCreator"]["_id"]]["_id"]
    assert sale["involvedUserIds"] == [sale["userSeller"]["_id"], sale["userCreator"]["_id"], "u-plain-id"]
    assert out["salesapp_commissions"][0]["user"]["_id"] == sale["userSeller"]["_id"]
    assert out["ecommerce_payments"][0]["createdByUserId"] == sale["userSeller"]["_id"]
    assert out["accounting_sales_orders"][0]["createdBy"]["user"]["_id"] == sale["userCreator"]["_id"]
    assert all(check_leaks.email_allowed(email) for email in anonymize.EMAIL_RE.findall(text))
    # Dict keys that are emails are replaced too.
    keyed = anonymize.scrub(anonymize.Anonymizer(), {"nikka@realcompany.ph": 3})
    assert list(keyed) == [anonymize.fake_email("nikka@realcompany.ph")]


def test_check_leaks_catches_planted_leaks_and_masks_them(tmp_path, capsys):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.json").write_text(
        json.dumps(
            [
                {
                    "_id": "ok@example.com",
                    "note": "ref 09012026441RGE, 0917 123 4567",
                    "t": "x@mail.example.com",
                }
            ]
        ),
        encoding="utf-8",
    )
    assert check_leaks.scan_dir(clean) == []
    assert check_leaks.main([str(clean)]) == 0
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "b.json").write_text(
        json.dumps(
            {
                "rows": [
                    {"_id": "ana.real@gmail.com", "x": {"ana.real@gmail.com": 1}},
                    {"img": REAL_URL, "name": "Ana Real Person"},
                ]
            }
        ),
        encoding="utf-8",
    )
    leaks = check_leaks.scan_dir(dirty, forbid=["ana real"])
    kinds = {(leak.kind, leak.count) for leak in leaks}
    assert kinds == {("email", 2), ("url", 1), ("forbidden:ana real", 1)}
    assert all(leak.path == dirty / "b.json" for leak in leaks)
    assert check_leaks.main([str(dirty), "--forbid", "ana real"]) == 1
    captured = capsys.readouterr().err
    assert (
        "ana.real@gmail.com" not in captured
        and REAL_URL not in captured
        and "Ana Real Person" not in captured
    )
    assert "3 leak(s) found" in captured and "ana…" in captured and "htt…" in captured


def test_extended_json_round_trip():
    when = datetime(2026, 10, 16, 8, 16, 36, 250000, tzinfo=UTC)
    encoded = anonymize.jsonable({"a": [when, {"b": when}], "n": 1})
    assert encoded["a"][0] == {"$date": "2026-10-16T08:16:36.250Z"}
    assert anonymize.from_jsonable(json.loads(json.dumps(encoded)))["a"][1]["b"] == when
    assert anonymize.iso_z(when) == "2026-10-16T08:16:36Z"
    assert anonymize.iso_z({"$date": {"$numberLong": "1792138596250"}}) == "2026-10-16T08:16:36Z"
    assert anonymize.iso_z(None) is None


@pytest.fixture(scope="module")
def planted() -> dict[str, list[dict]]:
    return plant.apply({}, AS_OF)


def by_id(docs: list[dict], key: str = "_id") -> dict[str, dict]:
    return {str(d[key]): d for d in docs}


def test_planting_is_idempotent_and_keeps_real_docs(planted):
    real = {"ecommerce_sales_orders": [{"_id": "real-1", "orderDate": AS_OF}]}
    once = plant.apply(real, AS_OF)
    twice = plant.apply(once, AS_OF)
    assert once == twice
    assert [d["_id"] for d in once["ecommerce_sales_orders"] if not plant.is_demo(d)] == ["real-1"]
    assert all(plant.is_demo(d) for docs in planted.values() for d in docs)


def test_paid_not_shipped_cases(planted):
    orders = by_id(planted["ecommerce_sales_orders"])
    acct = by_id(planted["accounting_sales_orders"])
    sales = by_id(planted["salesapp_sales"])
    served = by_id(planted["warehouse_served_orders"])
    payments = {p["salesOrderId"]: p for p in planted["ecommerce_payments"] if p["status"] == "confirmed"}
    for n, age in ((1, 7), (2, 3), (3, 1)):
        oid = f"DEMO-PNS-{n}"
        assert orders[oid]["paid"] is True and orders[oid]["deliveredAt"] is None
        assert orders[oid]["orderDate"] == AS_OF - timedelta(days=age)
        assert payments[oid]["amount"] == orders[oid]["grandTotal"] and payments[oid]["status"] == "confirmed"
        assert acct[oid]["paid"] is True and acct[oid]["balance"] == 0 and acct[oid]["delivered"] is False
        assert acct[oid]["totalPaymentReceived"] == orders[oid]["grandTotal"]
        assert oid not in served
        assert sales[oid]["paid"] is True and sales[oid]["delivered"] is False


def test_shipped_not_paid_cases(planted):
    acct = by_id(planted["accounting_sales_orders"])
    customers = by_id(planted["accounting_customers"])
    orders = by_id(planted["ecommerce_sales_orders"])
    served = by_id(planted["warehouse_served_orders"])
    sales = by_id(planted["salesapp_sales"])
    expected = {
        "DEMO-SNP-1": (40252.80, 30, 45),
        "DEMO-SNP-2": (12480.0, 15, 31),
        "DEMO-SNP-3": (3150.0, 0, 12),
    }
    for oid, (total, terms, age) in expected.items():
        order = acct[oid]
        assert order["grandTotal"] == total == order["balance"] and order["paid"] is False
        assert order["delivered"] is True and order["invoiceDate"] == AS_OF - timedelta(days=age)
        assert order["customer"]["paymentTerms"] == terms
        manager = order["customer"]["accountManager"]
        assert manager["name"] in {s["name"] for s in plant.SELLERS}
        customer = customers[order["customer"]["_id"]]
        assert customer["accountManager"] == manager and customer["paymentTerms"] == terms
        assert customer["accountBalance"] == {"current": total, "overdue": total}
        assert orders[oid]["status"] == "delivered" and orders[oid]["paid"] is False
        assert served[oid]["deliveryList"][0]["delivered"] is True and served[oid]["released"] is True
        assert sales[oid]["delivered"] is True and sales[oid]["paid"] is False
        assert orders[oid]["grandTotal"] == sales[oid]["totalSale"] == total


def test_payment_pending_confirmation(planted):
    pending = [p for p in planted["ecommerce_payments"] if p["status"] == "pending"]
    assert len(pending) == 1
    payment = pending[0]
    assert payment["salesOrderId"] == "DEMO-PPC-1" and payment["modeOfPayment"] == "GCash"
    assert payment["createdAt"] == AS_OF - timedelta(days=2)
    order = by_id(planted["accounting_sales_orders"])["DEMO-PPC-1"]
    assert order["balance"] > 0 and order["delivered"] is True and payment["amount"] == order["balance"]
    assert by_id(planted["ecommerce_sales_orders"])["DEMO-PPC-1"]["paid"] is False


def test_disputed_case(planted):
    order = by_id(planted["accounting_sales_orders"])["DEMO-DSP-1"]
    assert order["customer"]["name"] == "Marisol Dizon - Bayview Catering"
    assert order["invoiceDate"] == AS_OF - timedelta(days=70) and order["customer"]["paymentTerms"] == 30
    assert order["balance"] == order["grandTotal"] > 0 and order["delivered"] is True
    customer = by_id(planted["accounting_customers"])["DEMO-CUST-DSP-1"]
    assert customer["name"] == "Marisol Dizon - Bayview Catering"
    assert [n["content"] for n in customer["notesList"]] == [plant.DISPUTE_NOTE]
    assert plant.DISPUTE_NOTE == "Customer disputes invoice — damaged goods, awaiting credit memo"
    # Nobody else carries a note.
    assert all(not c["notesList"] for c in planted["accounting_customers"] if c["_id"] != "DEMO-CUST-DSP-1")


def test_commissions_are_exported_but_never_claimed(planted):
    commissions = {c["saleReference"]: c for c in planted["salesapp_commissions"]}
    assert set(commissions) == {c["id"] for c in plant.CASES}
    assert all(
        c["commissionClaimed"] is False and c["commissionClaimId"] is None for c in commissions.values()
    )


def test_planted_ids_and_amounts_agree_across_systems(planted):
    orders = by_id(planted["ecommerce_sales_orders"])
    acct = by_id(planted["accounting_sales_orders"])
    sales = by_id(planted["salesapp_sales"])
    assert set(orders) == set(acct) == set(sales) == {c["id"] for c in plant.CASES}
    for oid, order in orders.items():
        assert order["grandTotal"] == acct[oid]["grandTotal"] == sales[oid]["totalSale"]
        assert order["customerId"] == acct[oid]["customer"]["_id"] == sales[oid]["customer"]["_id"]
        assert order["customerName"] == acct[oid]["customer"]["name"] == sales[oid]["customer"]["name"]
        assert order["paid"] == acct[oid]["paid"] == sales[oid]["paid"]
        assert (order["status"] == "delivered") == acct[oid]["delivered"] == sales[oid]["delivered"]
        assert round(acct[oid]["netOfVat"] + acct[oid]["vatTotal"], 2) == order["grandTotal"]
        assert order["userSellerEmail"] == sales[oid]["userSeller"]["email"]
    for served in planted["warehouse_served_orders"]:
        assert served["customerName"] == orders[served["_id"]]["customerName"]
    users = {u["_id"] for u in planted["salesapp_users"]}
    assert {s["userSeller"]["_id"] for s in sales.values()} <= users


def test_fixtures_follow_the_contract(planted, tmp_path):
    built = fixtures.build(planted, AS_OF)
    assert set(built) == set(CONTRACT)
    for relative, (key, fields) in CONTRACT.items():
        body = built[relative]
        assert set(body) == {key}, relative
        assert body[key], relative
        for row in body[key]:
            assert set(row) == fields, (relative, set(row) ^ fields)
            if "currency" in row:
                assert row["currency"] == "PHP"
            for name, value in row.items():
                if name.endswith(("_at", "_date")) or name == "date":
                    assert value is None or ISO_Z.match(value), (relative, name, value)
                if name in (
                    "grand_total",
                    "amount",
                    "total",
                    "balance",
                    "balance_current",
                    "balance_overdue",
                ):
                    assert isinstance(value, int | float), (relative, name)
                if name == "notes":
                    assert isinstance(value, list) and all(isinstance(n, str) for n in value)
    written = fixtures.write(built, tmp_path)
    assert {p.relative_to(tmp_path).as_posix() for p in written} == set(CONTRACT)
    for path in written:  # the repo requires LF-only files with exactly one trailing newline
        raw = path.read_bytes()
        assert b"\r" not in raw and raw.endswith(b"}\n") and not raw.endswith(b"\n\n"), path
    assert (
        json.loads((tmp_path / "accounting" / "list_customers.json").read_text(encoding="utf-8"))
        == built["accounting/list_customers.json"]
    )


def test_fixtures_carry_the_planted_cases(planted):
    built = fixtures.build(planted, AS_OF)
    orders = by_id(built["ecommerce/list_orders.json"]["orders"], "id")
    assert set(orders) == {c["id"] for c in plant.CASES}
    assert orders["DEMO-PNS-1"]["paid"] is True and orders["DEMO-PNS-1"]["delivered_at"] is None
    served = {s["id"] for s in built["warehouse/list_served_orders.json"]["served_orders"]}
    assert not any(oid.startswith("DEMO-PNS") for oid in served) and "DEMO-SNP-1" in served
    acct = by_id(built["accounting/list_sales_orders.json"]["sales_orders"], "id")
    assert acct["DEMO-SNP-1"]["balance"] == 40252.80 and acct["DEMO-SNP-1"]["payment_terms_days"] == 30
    assert acct["DEMO-SNP-1"]["invoice_date"] == "2026-09-01T08:00:00Z"
    assert acct["DEMO-SNP-1"]["account_manager"] and acct["DEMO-SNP-1"]["account_manager_email"]
    customers = by_id(built["accounting/list_customers.json"]["customers"], "id")
    assert customers["DEMO-CUST-DSP-1"]["name"] == "Marisol Dizon - Bayview Catering"
    assert customers["DEMO-CUST-DSP-1"]["notes"] == [plant.DISPUTE_NOTE]
    pending = [p for p in built["ecommerce/list_payments.json"]["payments"] if p["status"] == "pending"]
    assert [p["order_id"] for p in pending] == ["DEMO-PPC-1"]


def test_fixtures_keep_a_spread_of_clean_orders_present_in_all_four_systems(planted):
    data = {name: list(docs) for name, docs in planted.items()}
    for day in range(60):
        when = AS_OF - timedelta(days=day)
        data["ecommerce_sales_orders"].append(
            {"_id": f"real-{day}", "orderDate": when, "customerId": f"c{day}"}
        )
        data["accounting_sales_orders"].append(
            {"_id": f"real-{day}", "invoiceDate": when, "customer": {"_id": f"c{day}"}}
        )
        data["accounting_customers"].append({"_id": f"c{day}", "name": f"Customer {day}"})
        if day % 3:  # every third order never reached the warehouse or the sales app (cancelled)
            data["warehouse_served_orders"].append({"_id": f"real-{day}", "createdDate": when})
            data["salesapp_sales"].append(
                {"_id": f"real-{day}", "date": when, "customer": {"_id": f"c{day}"}}
            )
        data["ecommerce_payments"].append({"_id": f"pay-{day}", "salesOrderId": f"real-{day}", "amount": 1.0})
        data["accounting_customer_payments"].append(
            {"_id": f"cpay-{day}", "orderReferenceOfPayment": f"real-{day}", "customer": {"_id": f"c{day}"}}
        )
    built = fixtures.build(data, AS_OF, clean=25)
    real = [o for o in built["ecommerce/list_orders.json"]["orders"] if o["id"].startswith("real-")]
    assert len(real) == 20  # 21 of the 31 in-window days exist everywhere; spread keeps 20 of them
    days = sorted(int(o["id"].removeprefix("real-")) for o in real)
    assert days[-1] <= 30 and all(day % 3 for day in days)
    customers = {c["id"] for c in built["accounting/list_customers.json"]["customers"]}
    assert {o["customer_id"] for o in real} <= customers
    assert_ids_agree_across_systems(built)


def assert_ids_agree_across_systems(built: dict[str, dict]) -> None:
    orders = {o["id"] for o in built["ecommerce/list_orders.json"]["orders"]}
    accounting = {o["id"] for o in built["accounting/list_sales_orders.json"]["sales_orders"]}
    sales = {s["id"] for s in built["salesapp/list_sales.json"]["sales"]}
    served = {s["id"] for s in built["warehouse/list_served_orders.json"]["served_orders"]}
    assert orders == accounting == sales
    # Paid-but-not-shipped is the one planted case with no served order, by design.
    assert served == orders - {c["id"] for c in plant.CASES if c["kind"] == "pns"}
    assert {p["order_id"] for p in built["ecommerce/list_payments.json"]["payments"]} <= orders
    assert {p["order_id"] for p in built["accounting/list_customer_payments.json"]["payments"]} <= orders


def test_fixture_ids_agree_across_systems_for_planted_data(planted):
    assert_ids_agree_across_systems(fixtures.build(planted, AS_OF))
