"""Ops reviewers in the live workspace: the New Machines reviewer network from `network_reviewers`, with 30
days of network work per reviewer; suspend and reinstate are audited and take effect at once."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from app import db as app_db
from app import ops_live, ops_reviewers, review_routing, settings
from app.errors import ApiProblem
from app.store import iso
from tests.test_live_catalog import As, _rows
from tests.test_ops_state import OPS, OPS_EMAIL, REASON
from tests.workforce_seed import (
    LOCK_WAIT_SECONDS,
    add_run,
    add_task,
    allow_network,
    attempt,
    hire,
    ids,
    join_network,
    live_api,
    network_task,
    public_id,
    wait_for_lock_waiters,
)

LIVE_REVIEWERS = "In the live workspace, network reviewers join from the reviewer portal and have no level."


@pytest.fixture
def api(db, monkeypatch):
    client, _ = live_api(db, monkeypatch)
    return client


@pytest.fixture
def ana(api) -> As:
    return As(api, "ana")


@pytest.fixture
def nina(api, db) -> As:
    user = As(api, "nina")
    join_network(db, "uid_nina")
    return user


def _taken(db, org_id: str, task_id: str, *, decided: datetime | None = None) -> None:
    """A task of `org_id` that Nina took through the network, decided at `decided` when given."""
    run_id = f"run_{task_id}"
    add_run(db, org_id, run_id)
    start = (decided or datetime.now(UTC)) - timedelta(minutes=6)
    marks = {"claimed_by": "uid_nina", "claimed_at": iso(start), "claimed_via": "network", "pay": 150}
    add_task(db, task_id, run_id, status="resolved" if decided else "open", payload=marks)
    if decided:
        db.execute(
            "UPDATE run_tasks SET decided_by = 'uid_nina', decided_at = %s WHERE id = %s", (decided, task_id)
        )
        db.commit()


def _move(api, verb: str, reviewer_id: str = "uid_nina"):
    return api.post(f"/v1/ops/reviewers/{reviewer_id}:{verb}", json={"reason": REASON}, headers=OPS)


def test_the_live_workforce_is_the_network_with_its_last_30_days(api, ana, nina, db):
    join_network(db, "uid_ana", enabled=False)  # turned off and not suspended: not listed
    now = datetime.now(UTC)
    _taken(db, ana.org_id, "ht_recent", decided=now - timedelta(days=2))
    _taken(db, ana.org_id, "ht_old", decided=now - timedelta(days=40))
    _taken(db, ana.org_id, "ht_open")
    res = api.get("/v1/ops/reviewers", headers=OPS)
    assert res.status_code == 200, res.text
    [row] = res.json()
    assert (row["id"], row["name"], row["email"], row["status"]) == (
        "uid_nina",
        "Nina Park",
        "nina@example.com",
        "active",
    )
    assert (row["languages"], row["skills"]) == (["en"], ["Reconciliation"])
    figures = (row["tasksDone30d"], row["earnings30d"]["amountMinor"], row["queue"], row["medianMinutes"])
    assert figures == (1, 150, 1, 6)
    assert api.get("/v1/ops/reviewers", params={"status": "suspended"}, headers=OPS).json() == []
    assert api.get("/v1/ops/reviewers", params={"status": "applicant"}, headers=OPS).json() == []


def test_a_suspended_reviewer_who_turned_the_network_off_stays_listed(api, nina, db):
    join_network(db, "uid_nina", enabled=False, status="suspended")
    [row] = api.get("/v1/ops/reviewers", headers=OPS).json()
    assert (row["id"], row["status"]) == ("uid_nina", "suspended")
    assert api.get("/v1/ops/reviewers", params={"status": "active"}, headers=OPS).json() == []


def test_suspending_is_audited_returns_the_claims_and_reinstating_offers_again(api, ana, nina, db):
    hire(db, ana.org_id, "network")
    allow_network(db, ana.org_id)
    _taken(db, ana.org_id, "ht_1")
    suspended = _move(api, "suspend")
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]
    assert ids(nina) == []
    assert nina.get("/v1/reviewer/profile").json()["suspended"] is True
    again = _move(api, "suspend")
    assert again.status_code == 409 and again.json()["code"] == "INVALID_TRANSITION"
    assert _move(api, "reinstate").json()["status"] == "active"
    assert ids(nina) == [public_id(db, "ht_1")]  # the open task is offered to her again
    audit = _rows(db, "SELECT actor_email, action, target_type, target_id, reason FROM ops_audit ORDER BY id")
    assert audit == [
        {
            "actor_email": OPS_EMAIL,
            "action": f"reviewer.{verb}",
            "target_type": "reviewer",
            "target_id": "uid_nina",
            "reason": REASON,
        }
        for verb in ("suspend", "reinstate")
    ]
    roles = _rows(
        db, "SELECT data->>'actor_role' AS role, data->>'summary' AS summary FROM ops_audit ORDER BY id"
    )
    assert roles == [
        {"role": "admin", "summary": "Status active → suspended"},
        {"role": "admin", "summary": "Status suspended → active"},
    ]


def test_a_suspension_leaves_team_claims_and_other_reviewers_alone(api, ana, nina, db):
    _taken(db, ana.org_id, "ht_net")
    add_run(db, ana.org_id, "run_team")
    add_task(db, "ht_team", "run_team", payload={"claimed_by": "uid_nina", "claimed_via": "team"})
    add_run(db, ana.org_id, "run_ben")
    add_task(db, "ht_ben", "run_ben", payload={"claimed_by": "uid_ben", "claimed_via": "network"})
    assert _move(api, "suspend").status_code == 200
    holders = _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks ORDER BY id")
    assert holders == [
        {"id": "ht_ben", "holder": "uid_ben"},
        {"id": "ht_net", "holder": None},
        {"id": "ht_team", "holder": "uid_nina"},
    ]


def test_an_unknown_reviewer_is_a_404(api):
    assert _move(api, "suspend", "uid_nobody").status_code == 404
    assert _move(api, "reinstate", "rev_sg_002").status_code == 404  # a demo fixture id


def test_approve_and_set_level_stay_refused_without_a_trace(api, nina, db):
    for path, body in (("uid_nina:approve", {}), ("uid_nina:setLevel", {"level": "qualified"})):
        res = api.post(f"/v1/ops/reviewers/{path}", json={"reason": REASON, **body}, headers=OPS)
        assert res.status_code == 409 and res.json()["code"] == "NOT_AVAILABLE_LIVE"
        assert res.json()["detail"] == LIVE_REVIEWERS
    assert _rows(db, "SELECT count(*) AS n FROM ops_audit") == [{"n": 0}]


def test_a_support_operator_cannot_suspend(api, nina, monkeypatch, db):
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "")
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", OPS_EMAIL)
    assert _move(api, "suspend").status_code == 403
    assert _rows(db, "SELECT status FROM network_reviewers") == [{"status": "active"}]


# --- a suspension against a claim in flight -----------------------------------------------------------
# Lock order: network_reviewers -> orgs -> org_members -> run_tasks (`app.review_routing`). Serial pytest
# only (`tests.workforce_seed.wait_for_lock_waiters`).


def _suspend(conn) -> None:
    ops_reviewers.move(conn, "uid_nina", "suspend", "active", "suspended", OPS_EMAIL, REASON)


def _suspend_and_commit() -> None:
    with app_db.connect() as conn:
        _suspend(conn)
        conn.commit()


def test_a_claim_waits_for_a_suspension_and_then_cannot_see_the_task(ana, nina, db):
    task = network_task(ana, nina, db)
    with (
        ThreadPoolExecutor(1) as pool,
        psycopg.connect(settings.test_database_url(), row_factory=dict_row) as other,
    ):
        _suspend(other)  # in progress: the profile row is locked and the change not committed yet
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        other.commit()
        result = claim.result(timeout=LOCK_WAIT_SECONDS)
    assert isinstance(result, ApiProblem) and result.status == 404
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


def test_a_suspension_waits_for_a_claim_in_flight_and_then_releases_it(ana, nina, db):
    task = network_task(ana, nina, db)
    with ThreadPoolExecutor(2) as pool, psycopg.connect(settings.test_database_url()) as other:
        # Hold the task row so the claim stops after taking the profile and org locks.
        other.execute("SELECT 1 FROM run_tasks WHERE id = 'ht_a' FOR UPDATE")
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        suspended = pool.submit(attempt, _suspend_and_commit)
        wait_for_lock_waiters(2)  # the suspension waits for the claim's profile lock
        other.rollback()
        claimed = claim.result(timeout=LOCK_WAIT_SECONDS)
        assert suspended.result(timeout=LOCK_WAIT_SECONDS) is None
    assert not isinstance(claimed, ApiProblem) and claimed["payload"]["claimed_by"] == "uid_nina"
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


# --- a tenant suspension and the network's claims -------------------------------------------------------


def _suspend_tenant(api, org_id: str):
    return api.post(f"/v1/ops/tenants/{org_id}:suspend", json={"reason": REASON}, headers=OPS)


def test_a_tenant_suspension_returns_its_network_claims_to_the_queue(api, ana, nina, db):
    hire(db, ana.org_id, "network")
    allow_network(db, ana.org_id)
    _taken(db, ana.org_id, "ht_net")
    add_run(db, ana.org_id, "run_team")
    add_task(db, "ht_team", "run_team", payload={"claimed_by": "uid_ana", "claimed_via": "team"})
    ben = As(api, "ben")
    _taken(db, ben.org_id, "ht_ben")  # another org's task Nina holds
    res = _suspend_tenant(api, ana.org_id)
    assert res.status_code == 200, res.text
    holders = _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks ORDER BY id")
    assert holders == [
        {"id": "ht_ben", "holder": "uid_nina"},
        {"id": "ht_net", "holder": None},
        {"id": "ht_team", "holder": "uid_ana"},
    ]
    [network] = _rows(db, "SELECT payload FROM run_tasks WHERE id = 'ht_net'")
    assert not {"claimed_by", "claimed_at", "claimed_via", "pay"} & set(network["payload"])


def _suspend_tenant_and_commit(org_id: str) -> None:
    with app_db.connect() as conn:
        ops_live.suspend(conn, org_id, OPS_EMAIL, REASON)
        conn.commit()


def test_a_tenant_suspension_waits_for_a_claim_in_flight_and_then_releases_it(ana, nina, db):
    task = network_task(ana, nina, db)
    with ThreadPoolExecutor(2) as pool, psycopg.connect(settings.test_database_url()) as other:
        # Hold the task row so the claim stops after taking the profile and org locks.
        other.execute("SELECT 1 FROM run_tasks WHERE id = 'ht_a' FOR UPDATE")
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        suspended = pool.submit(attempt, lambda: _suspend_tenant_and_commit(ana.org_id))
        wait_for_lock_waiters(2)  # the suspension waits for the claim's org lock
        other.rollback()
        claimed = claim.result(timeout=LOCK_WAIT_SECONDS)
        assert suspended.result(timeout=LOCK_WAIT_SECONDS) is None
    assert not isinstance(claimed, ApiProblem) and claimed["payload"]["claimed_by"] == "uid_nina"
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]
