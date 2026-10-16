"""The committed sandbox fixtures of the Order-to-Cash pack and of the custom business app connector hold
nothing traceable to the business they were first derived from: only fictional contact details and only
names the demo generator can produce. No database, no secrets."""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[3]
sys.path.insert(0, str(REPO / "scripts" / "demo_data"))

import anonymize  # noqa: E402
import check_leaks  # noqa: E402

FOLDERS = (
    REPO / "definitions" / "packs" / "order-to-cash-exception-desk" / "sandbox" / "custom-business-app",
    REPO / "definitions" / "connectors" / "sandbox" / "custom-business-app",
)
FILES = sorted(path for folder in FOLDERS for path in folder.glob("*.json"))
NAME_KEYS = ("customer_name", "name", "seller_name", "account_manager")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def rows(path: Path):
    body = json.loads(path.read_text(encoding="utf-8"))
    return [row for value in body.values() if isinstance(value, list) for row in value]


def test_both_sandbox_folders_are_found():
    assert len(FILES) >= 14 and all(folder.is_dir() for folder in FOLDERS)


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.parent.parent.name}/{p.name}")
def test_a_fixture_file_has_no_real_looking_data(path):
    found = check_leaks.scan_value(json.loads(path.read_text(encoding="utf-8")))
    # Emails only @example.com, no URL of any scheme, phones only +63 900 000 XXXX, no TIN-like number.
    assert {kind: len(values) for kind, values in found.items()} == {}


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.parent.parent.name}/{p.name}")
def test_every_name_is_one_the_generator_makes(path):
    names = [row[key] for row in rows(path) for key in NAME_KEYS if row.get(key)]
    odd = [name for name in names if not anonymize.is_generated_name(name)]
    assert odd == [], f"{len(odd)} name(s) in {path.name} are not generator-style"


def test_phones_and_emails_are_fictional_and_every_email_is_the_generator_s_for_its_name():
    for path in FILES:
        for row in rows(path):
            phone = row.get("phone")
            assert phone is None or anonymize.FICTIONAL_PHONE_RE.fullmatch(phone), path.name
            for name_key, email_key in (
                ("name", "email"),
                ("seller_name", "seller_email"),
                ("account_manager", "account_manager_email"),
            ):
                email = row.get(email_key)
                assert email is None or email.endswith("@example.com"), path.name
                if email is not None and name_key in row:
                    assert email == anonymize.email_from_name(row[name_key]), (path.name, email_key)


def test_no_timestamp_sits_on_a_round_minute_the_way_an_unshifted_export_would():
    """Synthetic rows have random seconds; the planted ones are the only 08:00:00 ones."""
    seconds = [
        value[-3:]
        for path in FILES
        for row in rows(path)
        for key, value in row.items()
        if isinstance(value, str) and ISO_Z.match(value) and not str(row["id"]).startswith("DEMO-")
    ]
    assert seconds and len(set(seconds)) > 20


def test_the_planted_cases_are_still_there():
    pack = FOLDERS[0]
    ids = {row["id"] for row in rows(pack / "list_store_orders.json")}
    assert {i for i in ids if i.startswith("DEMO-")} >= {
        "DEMO-PNS-1",
        "DEMO-PNS-2",
        "DEMO-PNS-3",
        "DEMO-SNP-1",
        "DEMO-SNP-2",
        "DEMO-SNP-3",
        "DEMO-PPC-1",
        "DEMO-DSP-1",
    }


def test_ids_still_join_across_every_file():
    """Re-keyed ids are the same value in every file they appear in."""
    pack = FOLDERS[0]
    orders = {row["id"] for row in rows(pack / "list_store_orders.json")}
    for name in ("list_store_payments.json", "list_customer_payments.json"):
        assert {row["order_id"] for row in rows(pack / name)} <= orders
    for name in ("list_sales_orders.json", "list_served_orders.json", "list_sales.json"):
        assert {row["id"] for row in rows(pack / name)} <= orders
    customers = {row["id"] for row in rows(pack / "list_customers.json")}
    assert {row["customer_id"] for row in rows(pack / "list_store_orders.json")} <= customers
    assert {row["customer_id"] for row in rows(pack / "list_sales_orders.json")} <= customers


def test_timestamps_are_still_iso_utc():
    for path in FILES:
        for row in rows(path):
            for key, value in row.items():
                if key.endswith(("_at", "_date", "date")) and isinstance(value, str):
                    assert ISO_Z.match(value), (path.name, key)
