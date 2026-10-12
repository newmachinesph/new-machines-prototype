"""Sync routes run in Starlette's threadpool, so requests really do run in parallel. Each test slows the step
between check and set, which is where an unlocked handler would interleave."""

import time
from concurrent.futures import ThreadPoolExecutor

from app.routers import approvals, runs
from app.store import get_store

PARALLEL = 8


def test_parallel_posts_with_one_key_create_one_run(client, monkeypatch):
    make = runs._new_run

    def slow_make(body):
        time.sleep(0.05)
        return make(body)

    monkeypatch.setattr(runs, "_new_run", slow_make)
    before = len(get_store().runs)
    body = {"packSlug": "order-payment-reconciliation", "input": "x", "budgetMinor": 5000}

    def post(_: int):
        return client.post("/v1/workflow-runs", json=body, headers={"Idempotency-Key": "retry-me"})

    with ThreadPoolExecutor(PARALLEL) as pool:
        responses = list(pool.map(post, range(PARALLEL)))

    assert [r.status_code for r in responses] == [202] * PARALLEL
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(get_store().runs) == before + 1


class SlowStatus:
    """Wraps an approval so that reading `status` pauses: the gap between the PENDING check and the write."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if name == "status":
            time.sleep(0.05)
        return value

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)


def test_parallel_approves_grant_once(client, monkeypatch):
    find = approvals.find_approval
    monkeypatch.setattr(approvals, "find_approval", lambda approval_id: SlowStatus(find(approval_id)))

    def approve(_: int):
        return client.post("/v1/approvals/apr_311:approve")

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(approve, range(2)))

    assert sorted(r.status_code for r in responses) == [200, 409]
    ok = next(r for r in responses if r.status_code == 200)
    conflict = next(r for r in responses if r.status_code == 409)
    assert ok.json()["status"] == "GRANTED"
    assert conflict.json()["code"] == "CONFLICT"
    assert [a.status for a in get_store().approvals if a.id == "apr_311"] == ["GRANTED"]
