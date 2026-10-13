"""Ops writes still backed by fixtures are refused in the live workspace: reviewers, marketplace packs and
incidents answer 409 NOT_AVAILABLE_LIVE without touching the store or the ops audit. The live runs list
holds real runs only. The demo workspace keeps all of them."""

import copy

import pytest
from fastapi.testclient import TestClient

from app import temporal_client
from app.store import get_store
from tests.test_live_catalog import As, Starts, _ready
from tests.test_ops_state import OPS, REASON

REVIEWERS = "In the live workspace, reviewers are managed by each company."
PACKS = "In the live workspace, packs are published as definitions."
INCIDENTS = "Incidents are not tracked in the live workspace yet."

NEW_PACK = {
    "name": "Live pack",
    "slug": "live-pack",
    "publisher": "New Machines",
    "category": "Finance",
    "outcome": "Something useful happens.",
    "description": "A pack that should not be created in the live workspace.",
    "riskClass": "low",
    "connectors": [],
    "humanReview": "None.",
}

# (path, body, detail): each would succeed in the demo workspace against the fixtures named.
REFUSED = [
    ("/v1/ops/reviewers/rev_ph_024:approve", {}, REVIEWERS),
    ("/v1/ops/reviewers/rev_ph_003:suspend", {}, REVIEWERS),
    ("/v1/ops/reviewers/rev_sg_002:reinstate", {}, REVIEWERS),
    ("/v1/ops/reviewers/rev_ph_017:setLevel", {"level": "qualified"}, REVIEWERS),
    ("/v1/ops/packs", NEW_PACK, PACKS),
    ("/v1/ops/packs/supplier-onboarding:submit", {}, PACKS),
    ("/v1/ops/packs/customs-paperwork-prep:approve", {}, PACKS),
    ("/v1/ops/packs/subscription-winback:reject", {}, PACKS),
    ("/v1/ops/packs/refund-triage:deprecate", {}, PACKS),
    ("/v1/ops/packs/legacy-order-export:republish", {}, PACKS),
    ("/v1/ops/packs/order-payment-reconciliation:certify", {}, PACKS),
    ("/v1/ops/incidents", {"title": "Live outage", "severity": "sev2", "services": ["api"]}, INCIDENTS),
    ("/v1/ops/incidents/inc_0042:update", {"status": "resolved", "text": "Fixed."}, INCIDENTS),
]


def _fixtures() -> tuple:
    """Everything a refused write could have changed, copied."""
    s = get_store()
    return copy.deepcopy(
        (s.reviewers, s.pack_listings, s.packs, s.pack_history, s.incidents, s.services, s.audit_log)
    )


@pytest.mark.parametrize(("path", "body", "detail"), REFUSED, ids=[p for p, _, _ in REFUSED])
def test_fixture_writes_are_refused_live_without_a_trace(live_ops: TestClient, db, path, body, detail):
    before = _fixtures()
    res = live_ops.post(path, json={"reason": REASON, **body}, headers=OPS)
    assert res.status_code == 409, res.text
    assert res.json()["code"] == "NOT_AVAILABLE_LIVE"
    assert res.json()["detail"] == detail
    assert _fixtures() == before
    assert db.execute("SELECT count(*) AS n FROM ops_audit").fetchone()["n"] == 0


def test_the_demo_workspace_still_accepts_fixture_writes(client: TestClient):
    res = client.post("/v1/ops/reviewers/rev_ph_024:approve", json={"reason": REASON})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active"
    declared = client.post(
        "/v1/ops/incidents",
        json={"title": "Demo outage", "severity": "sev2", "services": ["api"], "reason": REASON},
    )
    assert declared.status_code == 201, declared.text


def test_the_live_runs_list_holds_real_runs_only(live_ops: TestClient, db, monkeypatch):
    monkeypatch.setattr(temporal_client, "start_run", Starts())
    ana = As(live_ops, "ana")
    _ready(ana)
    started = ana.start()
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    org_name = db.execute("SELECT name FROM orgs WHERE id = %s", (ana.org_id,)).fetchone()["name"]
    fixture_ids = {r.id for r in get_store().run_summaries} | {r.id for r in get_store().ops_runs}

    runs = live_ops.get("/v1/ops/runs", headers=OPS).json()
    assert [r["id"] for r in runs] == [run_id]
    assert not fixture_ids & {r["id"] for r in runs}
    assert (runs[0]["real"], runs[0]["tenantId"], runs[0]["tenantName"]) == (True, ana.org_id, org_name)
    mine = live_ops.get("/v1/ops/runs", params={"tenant": ana.org_id}, headers=OPS).json()
    assert [r["id"] for r in mine] == [run_id]
    assert live_ops.get("/v1/ops/runs", params={"status": "FAILED"}, headers=OPS).json() == []


def test_the_demo_runs_list_keeps_its_fixture_runs(client: TestClient):
    ids = {r["id"] for r in client.get("/v1/ops/runs").json()}
    assert {r.id for r in get_store().ops_runs} <= ids
