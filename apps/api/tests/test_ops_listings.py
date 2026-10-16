"""Sub-project D, part 18: the ops review queue. Admins and owners decide, support reads; every decision is
audited with its note; the detail shows checks, the diff against the approved version, and the history."""

import pytest

from app import listing_diff
from app.defs import registry
from app.defs.model import Definition, path_for
from tests.live_seed import NOW, add_run
from tests.publishing_seed import add_listing, add_version, approve_and_list, defs_of
from tests.team_seed import clone_agent
from tests.test_ops_state import OPS, OPS_EMAIL, ana, live, ops_post, starts  # noqa: F401

BASE = "/v1/ops/listings"


@pytest.fixture
def queued(ana, db):  # noqa: F811
    """ana's agent listed at version 1, and version 2 (renamed) waiting for review."""
    agent = clone_agent(db, "finance-agent", ana.org_id, "matcher", title="Matcher")
    listing = add_listing(db, "agent", agent, ana.org_id, name="Matcher")
    approve_and_list(
        db, listing, add_version(db, listing, 1, defs_of(db, [("agent", agent)]), price_minor=30)
    )
    db.commit()  # a later transaction, so version 2 is submitted after version 1 (now() is per transaction)
    v = registry.latest(db, "agent", agent)
    registry.publish(
        db,
        Definition(
            "agent", agent, {**v.body, "name": "Matcher two"}, dict(v.files), path_for("agent", agent)
        ),
        "test",
        "two",
        source=registry.BUILDER,
    )
    add_version(db, listing, 2, defs_of(db, [("agent", agent)]), price_minor=40)
    db.commit()
    return listing, agent


def test_the_queue_lists_versions_waiting_for_review(live, queued):  # noqa: F811
    listing, _ = queued
    res = live.get(f"{BASE}?status=in_review", headers=OPS)
    assert res.status_code == 200
    [row] = res.json()
    assert row["id"] == listing and row["pending"]["definitionVersion"] == 2
    assert row["pending"]["price"]["amountMinor"] == 40


def test_the_detail_shows_the_diff_and_history(live, queued):  # noqa: F811
    listing, _ = queued
    detail = live.get(f"{BASE}/{listing}", headers=OPS).json()
    assert [v["definitionVersion"] for v in detail["versions"]] == [2, 1]
    [change] = detail["diff"]
    assert change["change"] == "changed" and "-name: Matcher" in change["unified"]
    assert "+name: Matcher two" in change["unified"]


def test_an_admin_approves_with_a_note_and_it_is_audited(live, queued, db):  # noqa: F811
    listing, agent = queued
    res = ops_post(live, f"{BASE}/{listing}:approve", reason="Clear and tested")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["price"]["amountMinor"] == 40 and body["history"][0]["action"] == "listing.approve"
    assert body["history"][0]["note"] == "Clear and tested"
    db.commit()
    [row] = db.execute("SELECT version FROM listed_definitions WHERE key = %s", (agent,)).fetchall()
    assert row["version"] == 2


def test_a_second_decision_is_an_invalid_transition(live, queued):  # noqa: F811
    listing, _ = queued
    assert ops_post(live, f"{BASE}/{listing}:reject", reason="Too vague").status_code == 200
    res = ops_post(live, f"{BASE}/{listing}:approve", reason="x")
    assert res.status_code == 409 and res.json()["code"] == "INVALID_TRANSITION"


def test_unlist_and_relist(live, queued, db):  # noqa: F811
    listing, agent = queued
    assert ops_post(live, f"{BASE}/{listing}:unlist", reason="Reported broken").json()["status"] == "unlisted"
    db.commit()
    assert db.execute("SELECT 1 FROM listed_definitions WHERE key = %s", (agent,)).fetchall() == []
    assert ops_post(live, f"{BASE}/{listing}:relist", reason="Fixed").json()["status"] == "listed"


def test_support_reads_but_cannot_decide(live, queued, monkeypatch):  # noqa: F811
    listing, _ = queued
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "")
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", OPS_EMAIL)
    assert live.get(BASE, headers=OPS).status_code == 200
    assert ops_post(live, f"{BASE}/{listing}:approve", reason="x").status_code == 403


def test_listing_the_queue_settles_finished_checks(live, ana, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", ana.org_id, "checked")
    add_run(db, "run_9501", ana.org_id, NOW, status="COMPLETED")
    listing = add_listing(db, "agent", agent, ana.org_id)
    add_version(db, listing, 1, defs_of(db, [("agent", agent)]), status="checking", check_run_id="run_9501")
    db.commit()
    rows = live.get(f"{BASE}?status=in_review", headers=OPS).json()
    assert listing in {r["id"] for r in rows}


def test_unknown_listing_is_404(live):  # noqa: F811
    assert live.get(f"{BASE}/lst_000000000000", headers=OPS).status_code == 404


def test_diff_of_a_first_version_adds_every_file(ana, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", ana.org_id, "fresh")
    db.commit()
    changes = listing_diff.diff(db, None, defs_of(db, [("agent", agent)]))
    assert changes and {c.change for c in changes} == {"added"}
