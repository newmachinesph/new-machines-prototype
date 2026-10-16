"""Publishing rows written straight into Postgres, so a test does not depend on `app.listings`: publishers,
listings, versions, listed definitions and fee lines. Nothing here commits."""

import secrets
from datetime import datetime

from psycopg.types.json import Jsonb

from app.defs import registry

OPS_EMAIL = "olga.ops@newmachin.es"
DECIDED = ("approved", "changes_requested", "rejected")


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def add_publisher(
    db,
    org_id: str,
    name: str = "Acme Labs",
    *,
    enabled: bool = True,
    description: str = "",
    payout_note: str = "",
) -> None:
    db.execute(
        "INSERT INTO publishers (org_id, name, description, payout_note, enabled) "
        "VALUES (%s, %s, %s, %s, %s)",
        (org_id, name, description, payout_note, enabled),
    )


def defs_of(db, refs: list[tuple[str, str]]) -> list[dict]:
    """Each ref at its latest registry version, as `listing_versions.definitions` holds them."""
    return [{"kind": k, "key": key, "version": registry.latest(db, k, key).version} for k, key in refs]


def add_listing(db, kind: str, key: str, org_id: str, *, name: str = "Listed item") -> str:
    listing_id = _id("lst")
    db.execute(
        "INSERT INTO listings (id, kind, definition_key, publisher_org_id, name) VALUES (%s, %s, %s, %s, %s)",
        (listing_id, kind, key, org_id, name),
    )
    return listing_id


def add_version(
    db,
    listing_id: str,
    definition_version: int,
    definitions: list[dict],
    *,
    status: str = "in_review",
    price_minor: int = 0,
    check_run_id: str | None = None,
    submitted_by: str = "ana@example.com",
    note: str = "",
) -> str:
    version_id = _id("lsv")
    decided = status in DECIDED
    db.execute(
        "INSERT INTO listing_versions (id, listing_id, definition_version, definitions, price_minor, status, "
        "check_run_id, submitted_by, decided_at, decided_by, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
        "CASE WHEN %s THEN now() END, %s, %s)",
        (
            version_id,
            listing_id,
            definition_version,
            Jsonb(definitions),
            price_minor,
            status,
            check_run_id,
            submitted_by,
            decided,
            OPS_EMAIL if decided else None,
            note,
        ),
    )
    return version_id


def approve_and_list(db, listing_id: str, version_id: str) -> None:
    db.execute(
        "UPDATE listing_versions SET status = 'approved', decided_at = now(), decided_by = %s "
        "WHERE id = %s AND status <> 'approved'",
        (OPS_EMAIL, version_id),
    )
    row = db.execute(
        "SELECT v.definitions, v.price_minor, l.publisher_org_id FROM listing_versions v "
        "JOIN listings l ON l.id = v.listing_id WHERE v.id = %s",
        (version_id,),
    ).fetchone()
    db.execute(
        "UPDATE listings SET status = 'listed', current_version_id = %s, price_minor = %s WHERE id = %s",
        (version_id, row["price_minor"], listing_id),
    )
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing_id,))
    for d in row["definitions"]:
        db.execute(
            "INSERT INTO listed_definitions (kind, key, version, listing_id, publisher_org_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (d["kind"], d["key"], d["version"], listing_id, row["publisher_org_id"]),
        )


def add_fee_line(
    db,
    run_id: str,
    listing_id: str,
    version_id: str,
    buyer: str,
    publisher: str,
    *,
    event_key: str = "pack",
    kind: str = "pack_run",
    unit_minor: int = 100,
    at: datetime | None = None,
) -> None:
    share = unit_minor * 80 // 100
    db.execute(
        "INSERT INTO fee_lines (run_id, event_key, listing_id, listing_version_id, buyer_org_id, "
        "publisher_org_id, kind, quantity, unit_minor, amount_minor, publisher_share_minor, "
        "platform_share_minor, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s, COALESCE(%s, now()))",
        (
            run_id,
            event_key,
            listing_id,
            version_id,
            buyer,
            publisher,
            kind,
            unit_minor,
            unit_minor,
            share,
            unit_minor - share,
            at,
        ),
    )
