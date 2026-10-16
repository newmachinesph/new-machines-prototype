"""Sub-project D, part 5: the listing state machine. Versions are checked, reviewed and decided; only the
approved bundle of a listed listing is exposed; unlist and relist are audited; every read is scoped."""

import re

import psycopg
import pytest
from psycopg.rows import dict_row

from app import listings, settings
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from tests.live_seed import NOW, add_org, add_run
from tests.publishing_seed import add_publisher, defs_of
from tests.team_seed import clone_agent

ACME, BUYER = "org_acme000000000001", "org_buyer00000000002"
OPS = "olga.ops@newmachin.es"
SHARED = f"{owners.org_key(ACME, 'kit')}/invoice"  # an own schema two of Acme's agents use


@pytest.fixture
def agent(defs):
    add_org(defs, ACME, "Acme")
    add_org(defs, BUYER, "Buyer Co")
    defs.commit()
    add_publisher(defs, ACME, "Acme Labs")
    key = clone_agent(defs, "finance-agent", ACME, "matcher", title="Matcher")
    defs.commit()
    return key


@pytest.fixture
def chaser(defs, agent):
    """A second Acme agent, and the own schema both agents share, at version 1."""
    key = clone_agent(defs, "finance-agent", ACME, "chaser", title="Chaser")
    _publish(defs, "schema", SHARED, {"type": "object", "title": "Invoice"})
    defs.commit()
    return key


def _publish(db, kind: str, key: str, body: dict, files: dict | None = None) -> None:
    """The next version of Acme's own kind/key."""
    registry.claim(db, kind, key, owners.org_owner(ACME), "test")
    d = Definition(kind=kind, key=key, body=body, files=dict(files or {}), path=path_for(kind, key))
    registry.publish(db, d, "test", "a test version", source=registry.BUILDER)


def _publish_agent_v2(db, key: str) -> None:
    latest = registry.latest(db, "agent", key)
    _publish(db, "agent", key, {**latest.body, "name": "Matcher 2"}, latest.files)


def _schema(version: int) -> dict:
    return {"kind": "schema", "key": SHARED, "version": version}


def _submit(
    db,
    key: str,
    *,
    status: str = "in_review",
    price: int = 30,
    run: str | None = None,
    version: int = 1,
    extra: tuple[dict, ...] = (),
    publisher: str = ACME,
) -> tuple[str, str]:
    return listings.submit(
        db,
        kind="agent",
        key=key,
        publisher_org_id=publisher,
        name="Matcher",
        definition_version=version,
        definitions=defs_of(db, [("agent", key)]) + list(extra),
        price_minor=price,
        checks=[{"name": "definition", "state": "passed", "detail": "No problems."}],
        status=status,
        submitted_by="ana@example.com",
        check_run_id=run,
    )


def _exposed(db) -> list[tuple]:
    rows = db.execute("SELECT kind, key, version FROM listed_definitions ORDER BY kind, key").fetchall()
    return [tuple(r.values()) for r in rows]


def _shared_row(db) -> tuple | None:
    row = db.execute(
        "SELECT version, listing_id FROM listed_definitions WHERE kind = 'schema' AND key = %s", (SHARED,)
    ).fetchone()
    return tuple(row.values()) if row else None


def test_approving_lists_the_version_and_exposes_its_bundle(defs, agent):
    listing, _ = _submit(defs, agent)
    assert listings.get(defs, listing)["status"] == "pending" and _exposed(defs) == []
    listings.decide(defs, listing, "approve", OPS, "Looks right", actor_role="admin")
    row = listings.get(defs, listing)
    assert (row["status"], row["price_minor"], row["name"]) == ("listed", 30, "Matcher")
    assert _exposed(defs) == [("agent", agent, 1)]
    [version] = listings.versions(defs, listing)
    assert (version.status, version.decided_by, version.note) == ("approved", OPS, "Looks right")
    [audit] = defs.execute("SELECT action, target_type, target_id FROM ops_audit").fetchall()
    assert tuple(audit.values()) == ("listing.approve", "listing", listing)


@pytest.mark.parametrize(
    ("verb", "status"), [("request-changes", "changes_requested"), ("reject", "rejected")]
)
def test_changes_and_rejections_expose_nothing(defs, agent, verb, status):
    listing, _ = _submit(defs, agent)
    listings.decide(defs, listing, verb, OPS, "Say what it reads")
    assert listings.versions(defs, listing)[0].status == status
    assert listings.get(defs, listing)["status"] == "pending" and _exposed(defs) == []


def test_only_a_version_in_review_can_be_decided(defs, agent):
    listing, _ = _submit(defs, agent, status="checking")
    with pytest.raises(listings.Transition, match="no version waiting for review"):
        listings.decide(defs, listing, "approve", OPS, "x")
    with pytest.raises(LookupError):
        listings.decide(defs, "lst_000000000000", "approve", OPS, "x")


def test_requesting_changes_or_rejecting_needs_a_note(defs, agent):
    listing, _ = _submit(defs, agent)
    for verb in ("request-changes", "reject"):
        with pytest.raises(listings.Transition, match="A note is required"):
            listings.decide(defs, listing, verb, OPS, "  ")
    assert listings.versions(defs, listing)[0].status == "in_review"
    assert defs.execute("SELECT count(*) AS n FROM ops_audit").fetchone()["n"] == 0


def test_exposing_a_listing_without_an_approved_version_does_nothing(defs, agent):
    listing, _ = _submit(defs, agent)
    listings.expose(defs, listing)
    assert _exposed(defs) == []


def test_one_open_version_at_a_time(defs, agent):
    listing, _ = _submit(defs, agent)
    with pytest.raises(listings.SubmissionOpen):
        _submit(defs, agent)
    listings.decide(defs, listing, "approve", OPS, "ok")
    again, _ = _submit(defs, agent, price=50)
    assert again == listing and listings.open_version(defs, listing).price.amount_minor == 50


def test_only_the_private_owner_can_submit_a_definition(defs, agent):
    with pytest.raises(listings.Transition, match="not a private definition of this workspace"):
        _submit(defs, "finance-agent")  # the platform's agent
    with pytest.raises(listings.Transition, match="not a private definition of this workspace"):
        _submit(defs, agent, publisher=BUYER)  # Acme's agent
    assert defs.execute("SELECT id FROM listings").fetchall() == []


def test_a_version_in_review_does_not_change_what_buyers_see(defs, agent):
    listing, _ = _submit(defs, agent)
    listings.decide(defs, listing, "approve", OPS, "ok")
    _publish_agent_v2(defs, agent)
    _submit(defs, agent, price=50, version=2)
    row = listings.market_info(defs, BUYER)[("agent", agent)]
    assert (row.price_minor, row.version, row.name) == (30, 1, "Matcher")
    assert listings.get(defs, listing)["price_minor"] == 30
    assert _exposed(defs) == [("agent", agent, 1)]


def test_a_new_approved_version_replaces_the_exposed_bundle_and_price(defs, agent):
    listing, _ = _submit(defs, agent)
    listings.decide(defs, listing, "approve", OPS, "ok")
    _publish_agent_v2(defs, agent)
    _submit(defs, agent, price=50, version=2)
    listings.decide(defs, listing, "approve", OPS, "ok")
    row = listings.get(defs, listing)
    assert (row["price_minor"], row["name"]) == (50, "Matcher 2")
    assert _exposed(defs) == [("agent", agent, 2)]
    market = listings.market_info(defs, BUYER)[("agent", agent)]
    assert (market.price_minor, market.version) == (50, 2)
    assert [v.status for v in listings.versions(defs, listing)] == ["approved", "approved"]


def test_listings_that_share_a_definition_keep_each_others_exposure(defs, agent, chaser):
    a, _ = _submit(defs, agent, extra=(_schema(1),))
    listings.decide(defs, a, "approve", OPS, "ok")
    b, _ = _submit(defs, chaser, extra=(_schema(1),))
    listings.decide(defs, b, "approve", OPS, "ok")
    assert _shared_row(defs) == (1, a)  # the same version: the row keeps its listing
    listings.move(defs, a, "unlist", OPS, "Reported broken")
    assert _shared_row(defs) == (1, b)  # still exposed, for the listing that is still listed
    assert _exposed(defs) == [("agent", chaser, 1), ("schema", SHARED, 1)]
    listings.move(defs, a, "relist", OPS, "Fixed")
    assert _shared_row(defs) == (1, b)
    listings.move(defs, b, "unlist", OPS, "x")
    assert _shared_row(defs) == (1, a)
    listings.move(defs, a, "unlist", OPS, "x")
    assert _exposed(defs) == []


def test_a_different_version_of_a_shared_definition_is_refused(defs, agent, chaser):
    a, _ = _submit(defs, agent, extra=(_schema(1),))
    listings.decide(defs, a, "approve", OPS, "ok")
    _publish(defs, "schema", SHARED, {"type": "object", "title": "Invoice, version 2"})
    b, _ = _submit(defs, chaser, extra=(_schema(2),))
    before = _exposed(defs)
    with pytest.raises(listings.Transition, match=re.escape(SHARED)):
        listings.decide(defs, b, "approve", OPS, "ok")
    assert listings.versions(defs, b)[0].status == "in_review"
    assert listings.get(defs, b)["status"] == "pending" and _exposed(defs) == before
    assert defs.execute("SELECT count(*) AS n FROM ops_audit").fetchone()["n"] == 1


def test_a_different_version_is_refused_when_the_listing_holds_the_shared_row(defs, agent, chaser):
    a, _ = _submit(defs, agent, extra=(_schema(1),))
    listings.decide(defs, a, "approve", OPS, "ok")
    b, _ = _submit(defs, chaser, extra=(_schema(1),))
    listings.decide(defs, b, "approve", OPS, "ok")
    assert _shared_row(defs) == (1, a)  # a holds the row b also needs
    _publish(defs, "schema", SHARED, {"type": "object", "title": "Invoice, version 2"})
    _submit(defs, agent, extra=(_schema(2),))
    before = _exposed(defs)
    with pytest.raises(listings.Transition, match=re.escape(SHARED) + ".*Chaser"):
        listings.decide(defs, a, "approve", OPS, "ok")
    assert listings.open_version(defs, a).status == "in_review"  # one transaction: same submitted_at
    assert _exposed(defs) == before and _shared_row(defs) == (1, a)
    assert defs.execute("SELECT count(*) AS n FROM ops_audit").fetchone()["n"] == 2


def test_relisting_with_a_different_version_of_a_shared_definition_is_refused(defs, agent, chaser):
    a, _ = _submit(defs, agent, extra=(_schema(1),))
    listings.decide(defs, a, "approve", OPS, "ok")
    b, _ = _submit(defs, chaser, extra=(_schema(1),))
    listings.decide(defs, b, "approve", OPS, "ok")
    listings.move(defs, b, "unlist", OPS, "x")
    _publish(defs, "schema", SHARED, {"type": "object", "title": "Invoice, version 2"})
    _submit(defs, chaser, extra=(_schema(2),))
    listings.decide(defs, b, "approve", OPS, "ok")  # unlisted: nothing exposed, nothing to refuse
    before = _exposed(defs)
    with pytest.raises(listings.Transition, match=re.escape(SHARED)):
        listings.move(defs, b, "relist", OPS, "Fixed")
    assert listings.get(defs, b)["status"] == "unlisted" and _exposed(defs) == before


def test_one_publishers_decisions_run_one_at_a_time(defs, agent, chaser):
    a, _ = _submit(defs, agent, extra=(_schema(1),))
    b, _ = _submit(defs, chaser, extra=(_schema(1),))
    defs.commit()
    listings.decide(defs, a, "approve", OPS, "ok")  # uncommitted: holds the publisher's listings
    # Requesting changes writes no shared row, so only the publisher lock can make it wait.
    with psycopg.connect(settings.test_database_url(), row_factory=dict_row) as other:
        other.execute("SET lock_timeout = '200ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            listings.decide(other, b, "request-changes", OPS, "Say what it reads")
        other.rollback()
        defs.commit()
        listings.decide(other, b, "request-changes", OPS, "Say what it reads")
        other.commit()
    assert listings.versions(defs, b)[0].status == "changes_requested"


def test_unlist_and_relist_move_the_exposure_and_are_audited(defs, agent):
    listing, _ = _submit(defs, agent)
    with pytest.raises(listings.Transition):
        listings.move(defs, listing, "unlist", OPS, "x")  # pending
    listings.decide(defs, listing, "approve", OPS, "ok")
    listings.move(defs, listing, "unlist", OPS, "Reported broken", actor_role="admin")
    assert listings.get(defs, listing)["status"] == "unlisted" and _exposed(defs) == []
    with pytest.raises(listings.Transition):
        listings.move(defs, listing, "unlist", OPS, "again")
    _submit(defs, agent)
    listings.decide(defs, listing, "approve", OPS, "ok")
    assert listings.get(defs, listing)["status"] == "unlisted"  # approval does not relist
    listings.move(defs, listing, "relist", OPS, "Fixed")
    assert listings.get(defs, listing)["status"] == "listed" and _exposed(defs) == [("agent", agent, 1)]
    actions = [r["action"] for r in defs.execute("SELECT action FROM ops_audit ORDER BY id").fetchall()]
    assert actions == ["listing.approve", "listing.unlist", "listing.approve", "listing.relist"]


def test_settling_checks_follows_the_sandbox_run(defs, agent):
    add_run(defs, "run_9201", ACME, NOW, status="COMPLETED")
    add_run(defs, "run_9202", ACME, NOW, status="FAILED")
    add_run(defs, "run_9203", ACME, NOW, status="RUNNING")
    other = clone_agent(defs, "finance-agent", ACME, "other")
    third = clone_agent(defs, "finance-agent", ACME, "third")
    a, _ = _submit(defs, agent, status="checking", run="run_9201")
    b, _ = _submit(defs, other, status="checking", run="run_9202")
    c, _ = _submit(defs, third, status="checking", run="run_9203")
    assert listings.settle_checks(defs, BUYER) == 0  # another org's versions are not touched
    defs.execute("UPDATE listings SET updated_at = now() - interval '1 day'")
    assert listings.settle_checks(defs, ACME) == 2
    changed = defs.execute("SELECT id FROM listings WHERE updated_at > now() - interval '1 hour'").fetchall()
    assert sorted(r["id"] for r in changed) == sorted([a, b])  # the ops queue sees them move
    assert listings.versions(defs, a)[0].status == "in_review"
    failed = listings.versions(defs, b)[0]
    assert failed.status == "checks_failed"
    assert [(c_.name, c_.state, c_.run_id) for c_ in failed.checks if c_.name == "sandbox"] == [
        ("sandbox", "failed", "run_9202")
    ]
    assert listings.versions(defs, c)[0].status == "checking"


def test_reads_are_scoped_to_the_publisher_and_market_info_to_other_workspaces(defs, agent):
    listing, _ = _submit(defs, agent)
    assert [r["id"] for r in listings.for_publisher(defs, ACME)] == [listing]
    assert listings.for_publisher(defs, BUYER) == []
    assert listings.market_info(defs, BUYER) == {}  # pending
    listings.decide(defs, listing, "approve", OPS, "ok")
    row = listings.market_info(defs, BUYER)[("agent", agent)]
    assert (row.publisher, row.price_minor, row.version, row.name) == ("Acme Labs", 30, 1, "Matcher")
    assert listings.market_info(defs, ACME) == {}  # never its own
    assert [r["id"] for r in listings.for_ops(defs, "listed")] == [listing]
    assert listings.for_ops(defs, "in_review") == []
