"""Live workspace set-up for the workforce tests: signed-in users across orgs, hires with a reviewer pool,
runs and human tasks written straight into Postgres, network reviewer rows, and the helpers the lock tests
share."""

import time
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import auth, settings, temporal_client
from app.defs import registry
from app.defs.loader import load_bundle
from app.errors import ApiProblem
from app.main import create_app
from app.store import reset_store
from tests.test_live_catalog import PACK, PROJECT, As, Starts
from tests.test_ops_state import OPS_CLAIMS, OPS_EMAIL

USERS = {
    "ana": {"sub": "uid_ana", "email": "ana@example.com", "email_verified": True, "name": "Ana Reyes"},
    "ben": {"sub": "uid_ben", "email": "ben@example.com", "email_verified": True, "name": "Ben Ito"},
    "rita": {"sub": "uid_rita", "email": "rita@example.com", "email_verified": True, "name": "Rita Cruz"},
    "mo": {"sub": "uid_mo", "email": "mo@example.com", "email_verified": True, "name": "Mo Diaz"},
    "nina": {"sub": "uid_nina", "email": "nina@example.com", "email_verified": True, "name": "Nina Park"},
}
# One record a review task shows (the `shared/review-items` shape).
SHOWN = [
    {
        "ref": "#1003",
        "date": "2026-10-12",
        "amount_minor": 2350,
        "currency": "USD",
        "flag": "Amount differs",
        "note": "Checked by finance.",
    }
]


def _verify(token, request, audience=None, clock_skew_in_seconds=0):
    claims = OPS_CLAIMS if token == "ops" else USERS[token]
    return {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, **claims}


class Signals:
    """Stands in for temporal_client.signal_human."""

    def __init__(self) -> None:
        self.human: list[tuple[str, str, str]] = []

    def __call__(self, run_id, task_id, outcome, note, resolutions=None) -> None:
        self.human.append((run_id, task_id, outcome))


def live_api(db, monkeypatch) -> tuple[TestClient, Signals]:
    """The API in the live workspace with every definition published; `ops` signs in as an ops admin."""
    env = {
        "NM_WORKSPACE": "live",
        "NM_RUNTIME": "temporal",
        "NM_CONNECTOR_MODE": "sandbox",
        "AUTH_MODE": "firebase",
        "FIREBASE_PROJECT_ID": PROJECT,
        "OPS_ADMIN_EMAILS": OPS_EMAIL,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    monkeypatch.setattr(temporal_client, "start_run", Starts())
    signals = Signals()
    monkeypatch.setattr(temporal_client, "signal_human", signals)
    reset_store()
    return TestClient(create_app()), signals


def put(user: As, path: str, **kw):
    return user.api.put(path, headers=user.headers, **kw)


def hire(db, org_id: str, pool: str, pack: str = PACK) -> None:
    db.execute(
        "INSERT INTO installations (org_id, pack_slug, pack_version, cap_minor, reviewer_pool, installed_by) "
        "VALUES (%s, %s, 1, 2000, %s, 'test') ON CONFLICT (org_id, pack_slug) "
        "DO UPDATE SET reviewer_pool = EXCLUDED.reviewer_pool",
        (org_id, pack, pool),
    )
    db.commit()


def add_run(db, org_id: str, run_id: str, pack: str = PACK) -> None:
    projection = {"id": run_id, "title": "Order & Payment Reconciliation", "status": "WAITING_FOR_HUMAN"}
    db.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
        "VALUES (%s, %s, %s, 'WAITING_FOR_HUMAN', '{}', %s, '{}')",
        (run_id, org_id, pack, Jsonb(projection)),
    )
    db.commit()


def add_task(
    db, task_id: str, run_id: str, *, at: datetime | None = None, status: str = "open", payload=None
) -> None:
    body = {"title": "Review the mismatches", "instructions": "Check each record.", "show": SHOWN}
    db.execute(
        "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload, created_at) "
        "VALUES (%s, %s, 'review', 'human', %s, %s, %s)",
        (task_id, run_id, status, Jsonb({**body, **(payload or {})}), at or datetime.now(UTC)),
    )
    db.commit()


def allow_network(db, org_id: str, allow: bool = True) -> None:
    db.execute("UPDATE orgs SET allow_network = %s WHERE id = %s", (allow, org_id))
    db.commit()


def join_network(db, user_id: str, *, enabled: bool = True, status: str = "active") -> None:
    email = f"{user_id.removeprefix('uid_')}@example.com"
    db.execute(
        "INSERT INTO network_reviewers (user_id, email, name, languages, skills, enabled, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id) "
        "DO UPDATE SET enabled = EXCLUDED.enabled, status = EXCLUDED.status",
        (user_id, email, "Nina Park", ["en"], ["Reconciliation"], enabled, status),
    )
    db.commit()


def ids(user: As) -> list[str]:
    """The ids of the user's open offers in /work."""
    return [t["id"] for t in user.get("/v1/human-tasks/eligible").json()]


def public_id(db, task_id: str) -> str:
    """The id a network reviewer knows the task by (`run_tasks.public_id`)."""
    db.commit()
    return db.execute("SELECT public_id FROM run_tasks WHERE id = %s", (task_id,)).fetchone()["public_id"]


# --- a change of who may hold a task against a claim in flight -------------------------------------------
# Lock order: network_reviewers -> orgs -> org_members -> run_tasks (`app.review_routing`). The lock tests
# need two pooled connections at once and assume serial pytest: `wait_for_lock_waiters` counts every backend
# of the test database.

LOCK_WAIT_SECONDS = 10
NETWORK_PROFILE = {
    "enabled": True,
    "name": "Nina Park",
    "languages": ["English"],
    "skills": ["Reconciliation"],
}


def network_task(ana: As, nina: As, db) -> str:
    """An open task of Ana's org offered to the network, with Nina reviewing for it. Returns the task's
    public id, the one Nina addresses it by; its own id is `ht_a`."""
    hire(db, ana.org_id, "network")
    allow_network(db, ana.org_id)
    add_run(db, ana.org_id, "run_a")
    add_task(db, "ht_a", "run_a")
    put(nina, "/v1/reviewer/profile", json=NETWORK_PROFILE)
    return public_id(db, "ht_a")


def attempt(call: Callable):
    """The call's result, or the API problem it raised."""
    try:
        return call()
    except ApiProblem as problem:
        return problem


def wait_for_lock_waiters(count: int) -> None:
    """Block until `count` backends of the test database wait on a row lock."""
    query = (
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND wait_event_type = 'Lock'"
    )
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    with psycopg.connect(settings.test_database_url(), autocommit=True) as watcher:
        while watcher.execute(query).fetchone()[0] < count:
            assert time.monotonic() < deadline, f"expected {count} transaction(s) waiting on a lock"
            time.sleep(0.02)
