"""Sub-project B, part 1: migration 008 and the three reviewer pools a hire can choose."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest

from app import db as app_db
from app import live_catalog, review_routing, settings
from app.auth import Actor
from app.defs import registry
from app.defs.loader import load_bundle
from app.errors import ApiProblem
from app.models.requests import InstallRequest
from tests.test_live_catalog import PACK, As, _rows
from tests.workforce_seed import (
    LOCK_WAIT_SECONDS,
    add_run,
    add_task,
    allow_network,
    attempt,
    live_api,
    network_task,
    wait_for_lock_waiters,
)

OTHER_PACK = "refund-triage"
NINA_NETWORK = {"claimed_by": "uid_nina", "claimed_via": "network", "pay": 150}

THEN_NETWORK = "your team first, then the New Machines reviewer network after 30 minutes"
TEAM_FOR_NOW = (
    "your team only for now. The reviewer network is off for your workspace, so your team reviews every task "
    "until an owner or admin allows the network on Reviewers"
)


@pytest.fixture
def api(db, monkeypatch):
    client, _ = live_api(db, monkeypatch)
    return client


@pytest.fixture
def ana(api) -> As:
    return As(api, "ana")


def _hire(user: As, pool=None):
    body = {"packSlug": PACK, "capMinor": 2000}
    if pool is not None:
        body["reviewerPool"] = pool
    return user.post(f"/v1/organizations/{user.org_id}/agent-installations", json=body)


def test_a_hire_defaults_to_team_then_network(ana, db):
    allow_network(db, ana.org_id)
    res = _hire(ana)
    assert res.status_code == 201, res.text
    assert res.json()["reviewerPool"] == "team_then_network"
    assert res.json()["summary"] == f"Spending cap $20.00 per run. Reviewers: {THEN_NETWORK}."
    assert _rows(db, "SELECT reviewer_pool FROM installations") == [{"reviewer_pool": "team_then_network"}]


@pytest.mark.parametrize(
    ("pool", "words"),
    [
        ("team", "your team only"),
        ("network", "the New Machines reviewer network"),
        ("team_then_network", THEN_NETWORK),
    ],
)
def test_each_pool_is_stored_and_shown_on_the_hired_pack(ana, db, pool, words):
    allow_network(db, ana.org_id)
    res = _hire(ana, pool)
    assert res.status_code == 201, res.text
    assert res.json()["summary"].endswith(f"Reviewers: {words}.")
    assert ana.get(f"/v1/workflow-packs/{PACK}").json()["reviewerPool"] == pool


@pytest.mark.parametrize("pool", ["network", "team_then_network"])
def test_with_the_network_off_the_summary_says_the_team_reviews_every_task(ana, pool):
    res = _hire(ana, pool)
    assert res.status_code == 201, res.text
    assert res.json()["summary"] == f"Spending cap $20.00 per run. Reviewers: {TEAM_FOR_NOW}."
    # The choice is kept, so it applies once the network is allowed.
    assert ana.get(f"/v1/workflow-packs/{PACK}").json()["reviewerPool"] == pool


def _publish_pack_v2(db) -> None:
    pack = load_bundle(settings.defs_dir()).get("pack", PACK)
    registry.publish(
        db, replace(pack, body={**pack.body, "outcome": "Edited in the console."}), "ops@x.com", "r"
    )
    db.commit()


def _pinned(db, org_id: str) -> list[dict]:
    return _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", org_id)


def test_saving_pack_settings_keeps_the_pinned_version(api, ana, db):
    assert _hire(ana, "team").status_code == 201
    _publish_pack_v2(db)
    res = _hire(ana, "network")
    assert res.status_code == 201, res.text
    assert _pinned(db, ana.org_id) == [{"pack_version": 1}]
    assert ana.get(f"/v1/workflow-packs/{PACK}").json()["reviewerPool"] == "network"
    # A first hire still pins the latest version.
    ben = As(api, "ben")
    assert _hire(ben).status_code == 201
    assert _pinned(db, ben.org_id) == [{"pack_version": 2}]


def test_with_the_network_off_a_team_hire_reads_as_before(ana):
    assert _hire(ana, "team").json()["summary"] == "Spending cap $20.00 per run. Reviewers: your team only."


@pytest.mark.parametrize("pool", [True, False, "team_and_pool", "anyone"])
def test_a_boolean_or_unknown_pool_is_refused(ana, pool):
    assert _hire(ana, pool).status_code == 422


def test_a_pack_not_hired_has_no_pool(ana):
    assert "reviewerPool" not in ana.get(f"/v1/workflow-packs/{PACK}").json()


def _holders(db) -> dict[str, str | None]:
    rows = _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks ORDER BY id")
    return {row["id"]: row["holder"] for row in rows}


def test_saving_the_pool_as_team_returns_the_packs_network_claims_to_the_queue(api, ana, db):
    allow_network(db, ana.org_id)
    assert _hire(ana, "network").status_code == 201
    ben = As(api, "ben")
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_net", "run_a", payload=NINA_NETWORK)
    add_task(db, "ht_team", "run_a", payload={"claimed_by": "uid_ana", "claimed_via": "team"})
    add_task(db, "ht_done", "run_a", status="resolved", payload=NINA_NETWORK)
    add_run(db, ana.org_id, "run_other", OTHER_PACK)  # another pack of Ana's org
    add_task(db, "ht_other", "run_other", payload=NINA_NETWORK)
    add_run(db, ben.org_id, "run_ben")  # the same pack, another org
    add_task(db, "ht_ben", "run_ben", payload=NINA_NETWORK)
    kept = {"ht_done": "uid_nina", "ht_other": "uid_nina", "ht_ben": "uid_nina", "ht_team": "uid_ana"}
    assert _hire(ana, "team_then_network").status_code == 201  # the network may still hold them
    assert _holders(db) == {**kept, "ht_net": "uid_nina"}
    assert _hire(ana, "team").status_code == 201
    assert _holders(db) == {**kept, "ht_net": None}
    [payload] = _rows(db, "SELECT payload FROM run_tasks WHERE id = 'ht_net'")
    assert not {"claimed_by", "claimed_at", "claimed_via", "pay"} & set(payload["payload"])


def test_a_pool_change_to_team_waits_for_a_claim_in_flight_and_then_releases_it(api, ana, db):
    nina = As(api, "nina")
    task = network_task(ana, nina, db)
    owner = Actor(user_id="uid_ana", org_id=ana.org_id, email="ana@example.com", name="Ana Reyes")
    body = InstallRequest.model_validate({"packSlug": PACK, "capMinor": 2000, "reviewerPool": "team"})
    with ThreadPoolExecutor(2) as pool, psycopg.connect(settings.test_database_url()) as other:
        # Hold the task row so the claim stops after taking the profile and org locks.
        other.execute("SELECT 1 FROM run_tasks WHERE id = 'ht_a' FOR UPDATE")
        claim = pool.submit(attempt, lambda: review_routing.claim(nina.org_id, "uid_nina", task))
        wait_for_lock_waiters(1)
        saved = pool.submit(attempt, lambda: live_catalog.install(owner, body))
        wait_for_lock_waiters(2)  # the save waits for the claim's org lock
        other.rollback()
        claimed = claim.result(timeout=LOCK_WAIT_SECONDS)
        assert not isinstance(saved.result(timeout=LOCK_WAIT_SECONDS), ApiProblem)
    assert not isinstance(claimed, ApiProblem) and claimed["payload"]["claimed_by"] == "uid_nina"
    assert _holders(db) == {"ht_a": None}
    assert _rows(db, "SELECT reviewer_pool FROM installations") == [{"reviewer_pool": "team"}]


def test_a_new_orgs_owner_is_a_reviewer_and_the_network_is_off(ana, db):
    assert _rows(db, "SELECT role, reviewer FROM org_members WHERE user_id = 'uid_ana'") == [
        {"role": "owner", "reviewer": True}
    ]
    assert _rows(db, "SELECT allow_network FROM orgs WHERE id = %s", ana.org_id) == [{"allow_network": False}]


def _undo_008(db) -> None:
    """The schema as it was before 008_workforce.sql."""
    db.execute("DROP TABLE network_reviewers")
    db.execute("DROP INDEX run_tasks_open_human")
    db.execute("ALTER TABLE orgs DROP COLUMN allow_network")
    db.execute("ALTER TABLE org_members DROP COLUMN reviewer")
    db.execute("ALTER TABLE org_members DROP CONSTRAINT org_members_role_check")
    db.execute(
        "ALTER TABLE org_members ADD CONSTRAINT org_members_role_check "
        "CHECK (role IN ('owner', 'admin', 'member'))"
    )
    db.execute("ALTER TABLE installations DROP CONSTRAINT installations_reviewer_pool_check")
    db.execute("ALTER TABLE installations ALTER COLUMN reviewer_pool DROP DEFAULT")
    db.execute(
        "ALTER TABLE installations ADD CONSTRAINT installations_reviewer_pool_check "
        "CHECK (reviewer_pool IN ('team', 'team_and_pool'))"
    )
    db.execute("DELETE FROM schema_migrations WHERE name = '008_workforce.sql'")


def test_migration_008_keeps_todays_reviewers_and_maps_the_old_pools(db):
    try:
        _undo_008(db)
        db.execute("INSERT INTO orgs (id, name) VALUES ('org_a', 'A')")
        members = [
            ("u1", "own@example.com", "owner", "active"),
            (None, "inv@example.com", "member", "invited"),
            ("u3", "old@example.com", "admin", "inactive"),
        ]
        for user_id, email, role, status in members:
            db.execute(
                "INSERT INTO org_members (org_id, user_id, email, role, status) "
                "VALUES ('org_a', %s, %s, %s, %s)",
                (user_id, email, role, status),
            )
        for slug, pool in (("pack-a", "team_and_pool"), ("pack-b", "team")):
            db.execute(
                "INSERT INTO installations (org_id, pack_slug, pack_version, cap_minor, reviewer_pool, "
                "installed_by) VALUES ('org_a', %s, 1, 2000, %s, 'u1')",
                (slug, pool),
            )
        db.commit()
        assert app_db.migrate(db) == ["008_workforce.sql"]
        assert _rows(db, "SELECT email, reviewer FROM org_members ORDER BY email") == [
            {"email": "inv@example.com", "reviewer": True},
            {"email": "old@example.com", "reviewer": False},
            {"email": "own@example.com", "reviewer": True},
        ]
        assert _rows(db, "SELECT pack_slug, reviewer_pool FROM installations ORDER BY pack_slug") == [
            {"pack_slug": "pack-a", "reviewer_pool": "team_then_network"},
            {"pack_slug": "pack-b", "reviewer_pool": "team"},
        ]
        assert _rows(db, "SELECT allow_network FROM orgs") == [{"allow_network": False}]
    finally:  # whatever failed above, `nm_test` keeps 008 for the tests after this one
        db.rollback()
        app_db.migrate(db)


def test_migration_009_gives_every_existing_task_its_own_public_id(db):
    try:
        db.execute("ALTER TABLE run_tasks DROP COLUMN public_id")
        db.execute("DELETE FROM schema_migrations WHERE name = '009_task_public_id.sql'")
        db.execute("INSERT INTO orgs (id, name) VALUES ('org_a', 'A')")
        db.execute(
            "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
            "VALUES ('run_1', 'org_a', 'p', 'RUNNING', '{}', '{}', '{}')"
        )
        for n in range(3):
            db.execute(
                "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) "
                "VALUES (%s, 'run_1', 'review', 'human', 'open', '{}')",
                (f"ht_run_1_review_{n}",),
            )
        db.commit()
        assert app_db.migrate(db) == ["009_task_public_id.sql"]
        ids = [r["public_id"] for r in _rows(db, "SELECT public_id FROM run_tasks")]
        assert len(set(ids)) == 3
        assert all(i.startswith("nt_") and len(i) == 23 and "run_" not in i for i in ids)
    finally:  # whatever failed above, `nm_test` keeps 009 for the tests after this one
        db.rollback()
        app_db.migrate(db)
