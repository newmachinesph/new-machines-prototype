"""Sub-project D, part 1: the publishing tables and the guarantees the database itself gives."""

import psycopg
import pytest

from tests.live_seed import NOW, add_org, add_run
from tests.publishing_seed import (
    add_fee_line,
    add_listing,
    add_publisher,
    add_version,
    approve_and_list,
    defs_of,
)
from tests.team_seed import clone_agent

ACME, BUYER = "org_acme000000000001", "org_buyer00000000002"


@pytest.fixture
def seeded(defs):
    add_org(defs, ACME, "Acme")
    add_org(defs, BUYER, "Buyer Co")
    defs.commit()
    agent = clone_agent(defs, "finance-agent", ACME, "matcher")
    add_publisher(defs, ACME)
    listing = add_listing(defs, "agent", agent, ACME, name="Matcher")
    version = add_version(defs, listing, 1, defs_of(defs, [("agent", agent)]), price_minor=50)
    defs.commit()
    return defs, agent, listing, version


def test_a_listing_is_listed_only_with_a_current_version(seeded):
    db, _, listing, _ = seeded
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE listings SET status = 'listed' WHERE id = %s", (listing,))
    db.rollback()


def test_a_listings_current_version_is_one_of_its_own(seeded):
    db, _, _, version = seeded
    other = add_listing(db, "agent", clone_agent(db, "finance-agent", ACME, "checker"), ACME, name="Checker")
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("UPDATE listings SET current_version_id = %s WHERE id = %s", (version, other))
    db.rollback()


def test_a_listing_has_one_open_version_at_a_time(seeded):
    db, agent, listing, _ = seeded
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_version(db, listing, 1, defs_of(db, [("agent", agent)]), status="checking")
    db.rollback()


def test_listed_definitions_name_existing_versions(seeded):
    db, agent, listing, version = seeded
    approve_and_list(db, listing, version)
    db.commit()
    [row] = db.execute("SELECT kind, key, version, publisher_org_id FROM listed_definitions").fetchall()
    assert (row["kind"], row["key"], row["version"], row["publisher_org_id"]) == ("agent", agent, 1, ACME)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "INSERT INTO listed_definitions (kind, key, version, listing_id, publisher_org_id) "
            "VALUES ('agent', %s, 99, %s, %s)",
            (f"{agent}-missing", listing, ACME),
        )
    db.rollback()


def test_fee_lines_split_exactly_and_never_change(seeded):
    db, _, listing, version = seeded
    approve_and_list(db, listing, version)
    add_run(db, "run_9001", BUYER, NOW)
    add_fee_line(db, "run_9001", listing, version, BUYER, ACME, unit_minor=5)
    db.commit()
    [line] = db.execute(
        "SELECT amount_minor, publisher_share_minor, platform_share_minor FROM fee_lines"
    ).fetchall()
    assert (line["amount_minor"], line["publisher_share_minor"], line["platform_share_minor"]) == (5, 4, 1)
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE fee_lines SET unit_minor = 0")
    db.rollback()
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("DELETE FROM fee_lines")
    db.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO fee_lines (run_id, event_key, listing_id, listing_version_id, buyer_org_id, "
            "publisher_org_id, kind, quantity, unit_minor, amount_minor, publisher_share_minor, "
            "platform_share_minor) VALUES ('run_9001', 'x', %s, %s, %s, %s, 'agent_call', 1, 5, 5, 3, 1)",
            (listing, version, BUYER, ACME),
        )
    db.rollback()


def test_a_workspace_never_pays_itself(seeded):
    db, _, listing, version = seeded
    add_run(db, "run_9002", ACME, NOW)
    with pytest.raises(psycopg.errors.CheckViolation):
        add_fee_line(db, "run_9002", listing, version, ACME, ACME)
    db.rollback()


def test_one_fee_line_per_charge(seeded):
    db, _, listing, version = seeded
    add_run(db, "run_9003", BUYER, NOW)
    add_fee_line(db, "run_9003", listing, version, BUYER, ACME)
    with pytest.raises(psycopg.errors.UniqueViolation):
        add_fee_line(db, "run_9003", listing, version, BUYER, ACME)
    db.rollback()


def test_a_fee_lines_version_belongs_to_its_listing(seeded):
    db, _, _, version = seeded
    other = add_listing(db, "agent", clone_agent(db, "finance-agent", ACME, "checker"), ACME, name="Checker")
    add_run(db, "run_9004", BUYER, NOW)
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_fee_line(db, "run_9004", other, version, BUYER, ACME)
    db.rollback()


@pytest.mark.parametrize("unknown", ["buyer", "publisher"])
def test_a_fee_lines_workspaces_exist(seeded, unknown):
    db, _, listing, version = seeded
    add_run(db, "run_9005", BUYER, NOW)
    db.commit()
    buyer, publisher = ("org_nobody", ACME) if unknown == "buyer" else (BUYER, "org_nobody")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_fee_line(db, "run_9005", listing, version, buyer, publisher)
    db.rollback()


def test_ops_audit_accepts_listings(seeded):
    db, _, listing, _ = seeded
    db.execute(
        "INSERT INTO ops_audit (actor_email, action, target_type, target_id) "
        "VALUES ('olga.ops@newmachin.es', 'listing.approve', 'listing', %s)",
        (listing,),
    )
    db.commit()
