"""Sub-project B, part 4: any user can turn on "Review for the network" in /work with a profile (name,
languages, skills). The profile is the user's own; turning it off takes their network claims back."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app import network_reviewers, org_reviewers, review_routing, settings
from app.auth import Actor
from app.errors import ApiProblem
from app.models.workforce import NetworkProfileRequest
from tests.test_live_catalog import As, _rows
from tests.workforce_seed import (
    LOCK_WAIT_SECONDS,
    NETWORK_PROFILE,
    add_run,
    add_task,
    allow_network,
    attempt,
    hire,
    ids,
    live_api,
    network_task,
    public_id,
    put,
    wait_for_lock_waiters,
)

PROFILE = NETWORK_PROFILE
OFF = NetworkProfileRequest(enabled=False, name="Nina Park")


@pytest.fixture
def api(db, monkeypatch):
    client, _ = live_api(db, monkeypatch)
    return client


@pytest.fixture
def ana(api) -> As:
    return As(api, "ana")


@pytest.fixture
def ben(api) -> As:
    return As(api, "ben")


@pytest.fixture
def nina(api) -> As:
    return As(api, "nina")


def _profile(user: As):
    return user.get("/v1/reviewer/profile")


def _save(user: As, **changes):
    return put(user, "/v1/reviewer/profile", json={**PROFILE, **changes})


def _holders(db) -> dict[str, str | None]:
    rows = _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks ORDER BY id")
    return {row["id"]: row["holder"] for row in rows}


def test_a_user_starts_outside_the_network(nina):
    res = _profile(nina)
    assert res.status_code == 200, res.text
    assert res.json() == {
        "enabled": False,
        "suspended": False,
        "name": "Nina Park",
        "languages": [],
        "skills": [],
    }


def test_turning_on_review_for_the_network_saves_the_profile(nina, db):
    res = _save(nina, languages=["English", " Tagalog ", "english"])
    assert res.status_code == 200, res.text
    assert res.json() == {
        "enabled": True,
        "suspended": False,
        "name": "Nina Park",
        "languages": ["English", "Tagalog"],
        "skills": ["Reconciliation"],
    }
    assert _profile(nina).json() == res.json()
    assert _rows(db, "SELECT user_id, email, enabled, status FROM network_reviewers") == [
        {"user_id": "uid_nina", "email": "nina@example.com", "enabled": True, "status": "active"}
    ]


def test_the_profile_is_the_users_own(nina, ben):
    _save(nina)
    assert _profile(ben).json()["enabled"] is False
    assert _profile(ben).json()["name"] == "Ben Ito"


def test_on_offers_network_tasks_and_off_returns_the_claims(ana, nina, db):
    hire(db, ana.org_id, "network")
    allow_network(db, ana.org_id)
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_a", "run_a")
    add_task(db, "ht_b", "run_a")
    assert ids(nina) == []
    _save(nina)
    assert sorted(ids(nina)) == sorted([public_id(db, "ht_a"), public_id(db, "ht_b")])
    assert nina.post(f"/v1/human-tasks/{public_id(db, 'ht_a')}:claim").status_code == 200
    assert _save(nina, enabled=False).json()["enabled"] is False
    assert ids(nina) == []
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks WHERE id = 'ht_a'") == [
        {"holder": None}
    ]


def test_turning_off_returns_only_the_users_own_network_claims(ana, ben, nina, db):
    hire(db, ana.org_id, "network")
    allow_network(db, ana.org_id)
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_a", "run_a")
    add_task(db, "ht_b", "run_a")
    add_run(db, nina.org_id, "run_n")  # Nina's own org, no hire: a team task she reviews as its owner
    add_task(db, "ht_n", "run_n")
    _save(nina)
    _save(ben, name="Ben Ito")
    assert nina.post(f"/v1/human-tasks/{public_id(db, 'ht_a')}:claim").status_code == 200
    assert ben.post(f"/v1/human-tasks/{public_id(db, 'ht_b')}:claim").status_code == 200
    assert nina.post("/v1/human-tasks/ht_n:claim").status_code == 200  # her own org's task: its own id
    _save(nina, enabled=False)
    assert _holders(db) == {"ht_a": None, "ht_b": "uid_ben", "ht_n": "uid_nina"}
    assert _profile(ben).json()["enabled"] is True


def test_a_suspended_reviewer_stays_suspended_when_saving(nina, db):
    _save(nina)
    db.execute("UPDATE network_reviewers SET status = 'suspended'")
    db.commit()
    res = _save(nina, name="Nina P.")
    assert res.json()["suspended"] is True and res.json()["name"] == "Nina P."


@pytest.mark.parametrize(
    "changes",
    [
        {"name": ""},
        {"name": "   "},
        {"languages": ["x"]},
        {"skills": ["s"] * 21},
        {"extra": 1},
        {"enabled": "yes"},
    ],
)
def test_a_bad_profile_is_refused(nina, changes):
    assert _save(nina, **changes).status_code == 422


def test_a_sign_in_without_an_email_keeps_the_stored_email(nina, db):
    _save(nina)
    network_reviewers.update(Actor(user_id="uid_nina", org_id=nina.org_id), OFF)
    assert _rows(db, "SELECT email FROM network_reviewers") == [{"email": "nina@example.com"}]


# --- a change of who may hold a task against a claim in flight -------------------------------------------
# Lock order and serial-pytest caveat: `tests.workforce_seed` (`wait_for_lock_waiters`).


def _nina(user: As) -> Actor:
    return Actor(user_id="uid_nina", org_id=user.org_id, email="nina@example.com", name="Nina Park")


def test_a_claim_waits_for_a_switch_off_and_then_cannot_see_the_task(ana, nina, db):
    task = network_task(ana, nina, db)
    # The connection closes before the pool waits for its thread, so a failed check never hangs the test.
    with ThreadPoolExecutor(1) as pool, psycopg.connect(settings.test_database_url()) as other:
        # A switch-off in progress: the profile row is locked and not committed yet.
        other.execute("UPDATE network_reviewers SET enabled = false WHERE user_id = 'uid_nina'")
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        other.commit()
        result = claim.result(timeout=LOCK_WAIT_SECONDS)
    assert isinstance(result, ApiProblem) and result.status == 404
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


def _profile_off(ana: As, nina: As):
    return network_reviewers.update(_nina(nina), OFF)


def _org_off(ana: As, nina: As):
    return org_reviewers.set_network(ana.org_id, "owner", False)


@pytest.mark.parametrize("switch_off", [_profile_off, _org_off], ids=["profile", "org"])
def test_a_switch_off_waits_for_a_claim_in_flight_and_then_releases_it(ana, nina, db, switch_off):
    task = network_task(ana, nina, db)
    with ThreadPoolExecutor(2) as pool, psycopg.connect(settings.test_database_url()) as other:
        # Hold the task row so the claim stops after taking the profile and org locks.
        other.execute("SELECT 1 FROM run_tasks WHERE id = 'ht_a' FOR UPDATE")
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        switched = pool.submit(attempt, lambda: switch_off(ana, nina))
        wait_for_lock_waiters(2)  # the switch-off waits for the claim's profile or org lock
        other.rollback()
        claimed = claim.result(timeout=LOCK_WAIT_SECONDS)
        assert not isinstance(switched.result(timeout=LOCK_WAIT_SECONDS), ApiProblem)
    assert not isinstance(claimed, ApiProblem) and claimed["payload"]["claimed_by"] == "uid_nina"
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


def _team_task(api, ana: As, db) -> As:
    """Rita, a Reviewer member of Ana's org, and an open team task of Ana's org."""
    assert ana.post(
        f"/v1/organizations/{ana.org_id}/reviewers", json={"email": "rita@example.com"}
    ).is_success
    rita = As(api, "rita")
    assert rita.post(f"/v1/invitations/{ana.org_id}:accept").status_code == 200
    hire(db, ana.org_id, "team")
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_a", "run_a")
    return rita


def _rita_claims(ana: As):
    return review_routing.claim(ana.org_id, "uid_rita", "ht_a")


def test_a_team_claim_waits_for_a_removal_and_then_cannot_see_the_task(api, ana, db):
    _team_task(api, ana, db)
    with ThreadPoolExecutor(1) as pool, psycopg.connect(settings.test_database_url()) as other:
        # A removal in progress: Rita's membership row is changed and not committed yet.
        other.execute("UPDATE org_members SET reviewer = false WHERE user_id = 'uid_rita'")
        claim = pool.submit(attempt, lambda: _rita_claims(ana))
        wait_for_lock_waiters(1)
        other.commit()
        result = claim.result(timeout=LOCK_WAIT_SECONDS)
    assert isinstance(result, ApiProblem) and result.status == 404
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


def test_a_removal_waits_for_a_team_claim_in_flight_and_then_releases_it(api, ana, db):
    _team_task(api, ana, db)
    with ThreadPoolExecutor(2) as pool, psycopg.connect(settings.test_database_url()) as other:
        # Hold the task row so the claim stops after taking the org and membership locks.
        other.execute("SELECT 1 FROM run_tasks WHERE id = 'ht_a' FOR UPDATE")
        claim = pool.submit(attempt, lambda: _rita_claims(ana))
        wait_for_lock_waiters(1)
        removed = pool.submit(attempt, lambda: org_reviewers.remove(ana.org_id, "owner", "rita@example.com"))
        wait_for_lock_waiters(2)  # the removal waits for the claim's membership lock
        other.rollback()
        claimed = claim.result(timeout=LOCK_WAIT_SECONDS)
        assert removed.result(timeout=LOCK_WAIT_SECONDS) is None
    assert not isinstance(claimed, ApiProblem) and claimed["payload"]["claimed_by"] == "uid_rita"
    assert _rows(db, "SELECT payload->>'claimed_by' AS holder FROM run_tasks") == [{"holder": None}]


def test_the_demo_workspace_has_no_network_profile(client):
    assert client.get("/v1/reviewer/profile").status_code == 404
    assert client.put("/v1/reviewer/profile", json=PROFILE).status_code == 404
