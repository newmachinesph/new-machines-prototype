"""The live workspace (NM_WORKSPACE=live, NM_RUNTIME=temporal), part 2: the marketplace from pack
definitions, hires and app connections per org, real runs gated on both, and runs, approvals, human tasks,
memory and earnings without fixture data. Every org-scoped table is checked across orgs."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import auth, ops_state, settings, temporal_client
from app import db as app_db
from app.defs import registry
from app.defs.loader import load_bundle
from app.main import create_app
from app.runtime import memory
from app.store import get_store, reset_store
from app.worker import activities

PROJECT = "nm-demo-test"
PACK = "order-payment-reconciliation"
PACK_NAME = "Order & Payment Reconciliation"
INPUT = {"since": "2026-10-06", "until": "2026-10-12"}
SHEET = "sandbox-reconciliation-sheet-00000001"  # the input schema's default spreadsheet_id
SEED_PACKS = {
    PACK: PACK_NAME,
    "overdue-invoice-follow-up": "Overdue Invoice Follow-up",
    "refund-triage": "Refund Triage",
}
USERS = {
    "ana": {"sub": "uid_ana", "email": "ana@example.com", "email_verified": True, "name": "Ana Reyes"},
    "ben": {"sub": "uid_ben", "email": "ben@example.com", "email_verified": True, "name": "Ben Ito"},
}


def _verify(token, request, audience=None, clock_skew_in_seconds=0):
    return {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, **USERS[token]}


class Starts:
    """Stands in for temporal_client.start_run."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, run_id, snapshot, input) -> None:
        self.calls.append((run_id, snapshot["org_id"], input))


@pytest.fixture
def starts(db, monkeypatch) -> Starts:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    recorder = Starts()
    monkeypatch.setattr(temporal_client, "start_run", recorder)
    return recorder


@pytest.fixture
def live(starts) -> TestClient:
    reset_store()
    return TestClient(create_app())


class As:
    """One signed-in user's calls."""

    def __init__(self, api: TestClient, user: str) -> None:
        self.api, self.headers = api, {"Authorization": f"Bearer {user}"}
        me = api.get("/v1/me", headers=self.headers)
        assert me.status_code == 200, me.text
        self.org_id = me.json()["orgId"]

    def get(self, path: str, **kw):
        return self.api.get(path, headers=self.headers, **kw)

    def post(self, path: str, **kw):
        return self.api.post(path, headers=self.headers, **kw)

    def delete(self, path: str, **kw):
        return self.api.delete(path, headers=self.headers, **kw)

    def hire(self, cap: int = 2000, pool: str = "team_then_network"):
        body = {"packSlug": PACK, "capMinor": cap, "reviewerPool": pool}
        return self.post(f"/v1/organizations/{self.org_id}/agent-installations", json=body)

    def connect(self, app: str):
        return self.post(f"/v1/connections/{app}:connect")

    def start(self, input=None, **kw):
        return self.post("/v1/workflow-runs", json=_start_body(input, **kw))


def _start_body(input=None, **kw) -> dict:
    return {"packSlug": PACK, "input": INPUT if input is None else input, "budgetMinor": 2000, **kw}


@pytest.fixture
def ana(live) -> As:
    return As(live, "ana")


@pytest.fixture
def ben(live) -> As:
    return As(live, "ben")


def _rows(db, query: str, *args) -> list[dict]:
    db.commit()
    return db.execute(query, args).fetchall()


def _ready(user: As) -> None:
    assert user.hire().status_code == 201
    for app in ("shopify", "stripe", "googlesheets"):
        assert user.connect(app).status_code == 200


def _add_run(db, org_id: str, run_id: str, spent: int = 0) -> None:
    money = {"amountMinor": spent, "currency": "USD"}
    zero = {"amountMinor": 0, "currency": "USD"}
    projection = {
        "id": run_id,
        "title": "Recon",
        "status": "COMPLETED",
        "spent": {"ai": money, "tools": zero},
    }
    db.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
        "VALUES (%s, %s, %s, 'COMPLETED', '{}', %s, '{}')",
        (run_id, org_id, PACK, Jsonb(projection)),
    )
    db.commit()


# --- marketplace ----------------------------------------------------------------------------------------


def test_the_marketplace_is_the_pack_definitions(ana):
    packs = ana.get("/v1/workflow-packs").json()
    assert sorted(p["slug"] for p in packs) == sorted(SEED_PACKS)
    pack = next(p for p in packs if p["slug"] == PACK)
    assert pack["name"] == PACK_NAME and pack["version"] == "1.0.0"
    assert pack["publisher"] == "New Machines Labs"
    assert pack["outcome"].startswith("Every order matched to a payment")
    assert pack["priceNote"].startswith("About $0.60 to $2.40")
    assert pack["riskClass"] == "medium" and pack["category"] == "Finance operations"
    assert pack["function"] == "finance-ops" and pack["industries"] == ["retail-commerce", "manufacturing"]
    assert pack["agents"] == ["finance-agent", "ops-agent"]
    assert [(c["app"], c["access"], c["mocked"]) for c in pack["connectors"]] == [
        ("Shopify", "read", True),
        ("Stripe", "read", True),
        ("Google Sheets", "write (approval)", True),
    ]
    assert pack["installed"] is False and "inputSchema" not in pack
    assert pack["estimate"]["humanMax"]["amountMinor"] == 2000


def test_pack_detail_carries_the_input_schema(ana):
    pack = ana.get(f"/v1/workflow-packs/{PACK}").json()
    assert pack["inputSchema"]["required"] == ["since", "until", "spreadsheet_id"]
    assert set(pack["inputSchema"]["properties"]) == {"since", "until", "spreadsheet_id"}
    assert ana.get("/v1/workflow-packs/weekly-inventory-report").status_code == 404  # a demo fixture pack
    assert ana.get("/v1/workflow-packs/nope").status_code == 404


def test_the_marketplace_lists_the_three_seed_packs(ana):
    packs = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}
    assert {slug: p["name"] for slug, p in packs.items()} == SEED_PACKS
    overdue, refunds = packs["overdue-invoice-follow-up"], packs["refund-triage"]
    assert overdue["agents"] == ["collections-agent", "writer-agent"]
    assert refunds["agents"] == ["refunds-agent", "writer-agent"]
    assert [c["app"] for c in overdue["connectors"]] == ["Stripe", "Gmail"]
    assert [c["app"] for c in refunds["connectors"]] == ["Gmail", "Shopify", "Stripe"]
    detail = ana.get("/v1/workflow-packs/overdue-invoice-follow-up").json()
    assert detail["inputSchema"]["required"] == ["as_of"]
    assert len(ana.get("/v1/agents").json()) == 6


def test_a_seed_pack_is_hired_connected_in_sandbox_and_started(ana, starts):
    slug = "overdue-invoice-follow-up"
    hired = ana.post(
        f"/v1/organizations/{ana.org_id}/agent-installations",
        json={"packSlug": slug, "capMinor": 1500, "reviewerPool": "team_then_network"},
    )
    assert hired.status_code == 201
    # Grants follow the pack's contract: this pack reads invoices, not charges, and writes mail drafts.
    stripe = ana.connect("stripe").json()
    assert stripe["grants"] == [
        {"install": "Overdue Invoice Follow-up", "capability": "invoices.read", "access": "read"}
    ]
    gmail = ana.connect("gmail").json()
    assert gmail["status"] == "sandbox"
    assert gmail["grants"] == [
        {"install": "Overdue Invoice Follow-up", "capability": "mail.write", "access": "write (approval)"}
    ]
    res = ana.start(packSlug=slug, input={"as_of": "2026-10-13"}, budgetMinor=1500)
    assert res.status_code == 202, res.json()
    assert starts.calls[-1][2] == {"as_of": "2026-10-13"}


def test_suggest_matches_over_pack_definitions(ana):
    found = ana.post(
        "/v1/workflow-packs:suggest", json={"text": "Match my Shopify orders to payments"}
    ).json()
    assert found["pack"]["slug"] == PACK and found["simulated"] is False
    assert found["steps"][0] == "Read the data it needs from Shopify, Stripe, Google Sheets."
    by_industry = ana.post("/v1/workflow-packs:suggest", json={"text": "something for manufacturing"}).json()
    assert by_industry["pack"]["slug"] == PACK
    none = ana.post("/v1/workflow-packs:suggest", json={"text": "bake a birthday cake"}).json()
    assert "pack" not in none and none["simulated"] is False


# --- install --------------------------------------------------------------------------------------------


def test_hiring_upserts_the_orgs_installation_only(ana, ben, db):
    before = [(p.slug, p.installed) for p in get_store().packs]
    res = ana.hire(cap=500, pool="team")
    assert res.status_code == 201, res.text
    assert res.json() == {
        "packSlug": PACK,
        "capMinor": 500,
        "reviewerPool": "team",
        "summary": "Spending cap $5.00 per run. Reviewers: your team only.",
    }
    assert ana.hire(cap=2000).status_code == 201  # again: updates, one row
    rows = _rows(
        db,
        "SELECT org_id, pack_slug, pack_version, cap_minor, reviewer_pool, installed_by FROM installations",
    )
    assert rows == [
        {
            "org_id": ana.org_id,
            "pack_slug": PACK,
            "pack_version": 1,
            "cap_minor": 2000,
            "reviewer_pool": "team_then_network",
            "installed_by": "uid_ana",
        }
    ]
    assert [(p.slug, p.installed) for p in get_store().packs] == before  # the demo store is untouched
    assert ana.get("/v1/workflow-packs").json()[0]["installed"] is True
    assert ana.get(f"/v1/workflow-packs/{PACK}").json()["installed"] is True
    # Another org sees the pack as not hired and cannot hire into Ana's org.
    assert ben.get("/v1/workflow-packs").json()[0]["installed"] is False
    body = {"packSlug": PACK, "capMinor": 500, "reviewerPool": "team_then_network"}
    assert ben.post(f"/v1/organizations/{ana.org_id}/agent-installations", json=body).status_code == 403


def test_hiring_checks_the_pack_and_cap(ana):
    url = f"/v1/organizations/{ana.org_id}/agent-installations"
    fixture_only = {
        "packSlug": "weekly-inventory-report",
        "capMinor": 500,
        "reviewerPool": "team_then_network",
    }
    assert ana.post(url, json=fixture_only).status_code == 404
    assert (
        ana.post(url, json={"packSlug": PACK, "capMinor": 0, "reviewerPool": "team_then_network"}).status_code
        == 422
    )
    assert ana.post(url, json={"packSlug": PACK, "capMinor": 500, "reviewerPool": "maybe"}).status_code == 422


# --- connections ----------------------------------------------------------------------------------------


def test_connections_are_the_apps_hired_packs_use(ana):
    assert ana.get("/v1/connections").json() == []
    ana.hire()
    listed = ana.get("/v1/connections").json()
    assert [(c["key"], c["app"], c["status"]) for c in listed] == [
        ("shopify", "Shopify", "not_connected"),
        ("stripe", "Stripe", "not_connected"),
        ("googlesheets", "Google Sheets", "not_connected"),
    ]
    assert all(c["grants"] == [] and "mode" not in c for c in listed)


def test_connecting_in_sandbox_mode_grants_the_tools_of_hired_packs(ana, db):
    ana.hire()
    shopify = ana.connect("shopify").json()
    assert shopify["status"] == "sandbox" and shopify["provider"] == "Mock" and shopify["mode"] == "sandbox"
    assert shopify["account"] == "Sandbox data"
    assert shopify["grants"] == [{"install": PACK_NAME, "capability": "orders.read", "access": "read"}]
    sheets = ana.connect("Google Sheets").json()  # by app name too
    assert sheets["key"] == "googlesheets"
    assert sheets["grants"] == [
        {"install": PACK_NAME, "capability": "sheets.write", "access": "write (approval)"}
    ]
    [row] = _rows(db, "SELECT org_id, status, mode, connected_by FROM connections WHERE app = 'shopify'")
    assert row == {"org_id": ana.org_id, "status": "sandbox", "mode": "sandbox", "connected_by": "uid_ana"}
    assert ana.connect("nope").status_code == 404


def test_an_app_connected_before_the_hire_gains_the_packs_grants(ana):
    assert ana.connect("stripe").json()["grants"] == []
    assert [c["key"] for c in ana.get("/v1/connections").json()] == ["stripe"]
    ana.hire()
    stripe = next(c for c in ana.get("/v1/connections").json() if c["key"] == "stripe")
    assert stripe["grants"] == [{"install": PACK_NAME, "capability": "payments.read", "access": "read"}]


def test_disconnect_and_revoke_update_the_orgs_row(ana, db):
    ana.hire()
    ana.connect("shopify")
    ana.connect("stripe")
    query = {"app": "Stripe", "install": PACK_NAME, "capability": "payments.read"}
    assert ana.delete("/v1/grants", params=query).status_code == 204
    assert ana.delete("/v1/grants", params=query).status_code == 404
    stripe = next(c for c in ana.get("/v1/connections").json() if c["key"] == "stripe")
    assert stripe["status"] == "sandbox" and stripe["grants"] == []
    gone = ana.post("/v1/connections/Shopify:disconnect").json()
    assert gone["status"] == "not_connected" and gone["grants"] == []
    rows = _rows(db, "SELECT app, status FROM connections ORDER BY app")
    assert rows == [{"app": "shopify", "status": "not_connected"}, {"app": "stripe", "status": "sandbox"}]


def test_another_org_can_neither_see_nor_change_an_orgs_connections(ana, ben, db):
    ana.hire()
    ana.connect("shopify")
    assert ben.get("/v1/connections").json() == []
    ben.post("/v1/connections/shopify:disconnect")
    query = {"app": "shopify", "install": PACK_NAME, "capability": "orders.read"}
    assert ben.delete("/v1/grants", params=query).status_code == 404
    [row] = _rows(db, "SELECT org_id, status, grants FROM connections WHERE org_id = %s", ana.org_id)
    assert row["status"] == "sandbox" and len(row["grants"]) == 1
    assert ana.get("/v1/connections").json()[0]["status"] == "sandbox"


# --- start a run ----------------------------------------------------------------------------------------


def test_a_run_needs_the_pack_hired(ana, starts):
    res = ana.start()
    assert res.status_code == 409 and res.json()["code"] == "PACK_NOT_HIRED"
    assert res.json()["detail"] == f"Add {PACK_NAME} before starting a run."
    assert starts.calls == []


def test_a_run_needs_every_app_connected(ana, starts):
    ana.hire()
    res = ana.start()
    assert res.status_code == 409 and res.json()["code"] == "APPS_NOT_CONNECTED"
    assert (
        res.json()["detail"]
        == f"Connect Shopify, Stripe and Google Sheets before starting a run of {PACK_NAME}."
    )
    ana.connect("shopify")
    ana.connect("stripe")
    assert ana.start().json()["detail"].startswith("Connect Google Sheets before")
    assert starts.calls == []


def test_the_input_must_match_the_packs_input_schema(ana, starts):
    _ready(ana)
    res = ana.start(input={"since": "last week", "extra": 1})
    assert res.status_code == 422 and res.json()["code"] == "INVALID_INPUT"
    errors = res.json()["errors"]
    assert [e["path"] for e in errors] == ["extra", "since", "until"]  # unknown, bad date, missing
    assert errors[0]["message"] == "extra is not a field this pack takes."
    assert errors[2]["message"] == "until is required."
    assert all(e["kind"] == "input" and e["key"] == PACK for e in errors)
    assert starts.calls == []


def test_every_missing_field_is_named_once(ana, starts):
    _ready(ana)
    res = ana.start(input={})
    assert res.status_code == 422
    assert [e["path"] for e in res.json()["errors"]] == ["since", "until"]
    assert res.json()["detail"] == "The input is not valid. since is required."


def test_nested_input_errors_keep_their_path():
    from app import real_runs
    from app.errors import ApiProblem

    schema = {
        "type": "object",
        "properties": {
            "range": {
                "type": "object",
                "required": ["from", "to"],
                "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
                "additionalProperties": False,
            }
        },
    }
    with pytest.raises(ApiProblem) as raised:
        real_runs.check_input("p", {"range": {"to": 3, "odd": 1}}, schema)
    assert [(i.path, i.message) for i in raised.value.errors] == [
        ("range/from", "from is required."),
        ("range/odd", "odd is not a field this pack takes."),
        ("range/to", "3 is not of type 'string'"),
    ]


def test_a_ready_pack_starts_a_real_run_for_the_org(ana, starts, db):
    _ready(ana)
    res = ana.start()
    assert res.status_code == 202, res.text
    run = res.json()
    assert starts.calls == [(run["id"], ana.org_id, {**INPUT, "spreadsheet_id": SHEET})]
    [row] = _rows(db, "SELECT org_id, input FROM runs")
    assert row == {"org_id": ana.org_id, "input": {**INPUT, "spreadsheet_id": SHEET}}
    text = ana.start(input="2026-10-01..2026-10-02")  # the older free-text form still works
    assert text.status_code == 202 and starts.calls[-1][2] == {
        "since": "2026-10-01",
        "until": "2026-10-02",
        "spreadsheet_id": SHEET,
    }


def test_a_budget_over_the_hires_per_run_cap_is_refused(ana, starts):
    _ready(ana)
    ana.hire(cap=500)
    res = ana.start(budgetMinor=501)
    assert res.status_code == 409 and res.json()["code"] == "RUN_BUDGET_OVER_CAP"
    assert "$5.00 per run" in res.json()["detail"]
    assert ana.start(budgetMinor=500).status_code == 202
    assert len(starts.calls) == 1


def test_a_hired_pack_carries_its_per_run_cap(ana):
    assert ana.get(f"/v1/workflow-packs/{PACK}").json().get("perRunCap") is None
    ana.hire(cap=700)
    detail = ana.get(f"/v1/workflow-packs/{PACK}").json()
    assert detail["perRunCap"] == {"amountMinor": 700, "currency": "USD"}
    listed = next(p for p in ana.get("/v1/workflow-packs").json() if p["slug"] == PACK)
    assert listed["perRunCap"]["amountMinor"] == 700


def test_a_pack_another_org_hired_cannot_be_started(ana, ben, starts):
    _ready(ana)
    res = ben.start()
    assert res.status_code == 409 and res.json()["code"] == "PACK_NOT_HIRED"
    assert starts.calls == []


def test_one_idempotency_key_from_two_orgs_starts_two_runs(ana, ben, starts):
    _ready(ana)
    _ready(ben)
    key = {"Idempotency-Key": "same-key"}
    first = ana.api.post("/v1/workflow-runs", json=_start_body(), headers={**ana.headers, **key})
    second = ben.api.post("/v1/workflow-runs", json=_start_body(), headers={**ben.headers, **key})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert [c[1] for c in starts.calls] == [ana.org_id, ben.org_id]
    again = ana.api.post("/v1/workflow-runs", json=_start_body(), headers={**ana.headers, **key})
    assert again.json()["id"] == first.json()["id"] and len(starts.calls) == 2


def test_no_run_starts_once_the_months_spend_reaches_the_cap(ana, starts, db):
    _ready(ana)
    _add_run(db, ana.org_id, "run_old", spent=2500)  # the default monthly cap
    res = ana.start()
    assert res.status_code == 409 and res.json()["code"] == "SPEND_CAP"
    assert "$25.00" in res.json()["detail"]
    assert starts.calls == []


def test_the_platform_pause_still_blocks_live_runs(ana, starts, db):
    _ready(ana)
    ops_state.set_paused(db, True, "ops@newmachin.es", "Testing the pause")
    db.commit()
    res = ana.start()
    assert res.status_code == 409 and res.json()["code"] == "PLATFORM_PAUSED"
    assert starts.calls == []


def test_an_unknown_or_fixture_pack_cannot_start(ana):
    assert ana.start(packSlug="weekly-inventory-report").status_code == 404
    assert ana.start(packSlug="nope").status_code == 404


# --- runs, approvals, human tasks: real rows only -------------------------------------------------------


def test_runs_are_real_and_the_orgs_own(ana, ben):
    fixture_run = get_store().run_summaries[0].id
    assert ana.get("/v1/workflow-runs").json() == []
    assert ana.get(f"/v1/workflow-runs/{fixture_run}").status_code == 404
    _ready(ana)
    run_id = ana.start().json()["id"]
    assert [r["id"] for r in ana.get("/v1/workflow-runs").json()] == [run_id]
    assert ana.get(f"/v1/workflow-runs/{run_id}").status_code == 200
    assert ben.get("/v1/workflow-runs").json() == []
    assert ben.get(f"/v1/workflow-runs/{run_id}").status_code == 404
    assert ben.get(f"/v1/workflow-runs/{run_id}/receipt").status_code == 404


def test_approvals_and_human_tasks_have_no_fixtures(ana):
    assert ana.get("/v1/approvals").json() == []
    assert ana.post("/v1/approvals/apr_311:approve").status_code == 404
    assert ana.get("/v1/human-tasks/eligible").json() == []
    assert ana.get("/v1/human-tasks/ht_011").status_code == 404
    assert ana.post("/v1/human-tasks/ht_011:claim").status_code == 404
    review = {"verdict": "APPROVED", "feedbackText": "ok", "recordCalls": {}}
    assert ana.post("/v1/human-tasks/ht_011:submit", json=review).status_code == 404


def test_approvals_and_tasks_of_an_orgs_runs_stay_in_that_org(ana, ben, db):
    _add_run(db, ana.org_id, "run_a")
    for kind, status in (("approval", "pending"), ("human", "open")):
        db.execute(
            "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) "
            "VALUES (%s, 'run_a', 'n', %s, %s, %s)",
            (f"{kind}_a", kind, status, Jsonb({"title": "Check"})),
        )
    db.commit()
    assert [a["id"] for a in ana.get("/v1/approvals").json()] == ["approval_a"]
    assert [t["id"] for t in ana.get("/v1/human-tasks/eligible").json()] == ["human_a"]
    assert ana.get("/v1/human-tasks/eligible").json()[0]["payTerms"] == "Team review: unpaid"
    assert ben.get("/v1/approvals").json() == [] and ben.get("/v1/human-tasks/eligible").json() == []
    assert ben.post("/v1/approvals/approval_a:approve").status_code == 404
    assert ben.post("/v1/approvals/approval_a:decline").status_code == 404
    assert _rows(db, "SELECT status, decided_by FROM run_tasks WHERE id = 'approval_a'") == [
        {"status": "pending", "decided_by": None}
    ]
    assert ben.post("/v1/human-tasks/human_a:claim").status_code == 404


# --- memory ---------------------------------------------------------------------------------------------


def _remember(db, text: str, source: str, org_id: str | None) -> str:
    item = memory.remember(db, "retail-commerce", text, source, "workflow", org_id=org_id)
    db.commit()
    return item["id"]


def test_memory_is_the_orgs_own_and_the_shared_items(ana, ben, db):
    seeds = {r["id"] for r in _rows(db, "SELECT id FROM memory_items WHERE source = 'seed'")}
    assert seeds
    own = _remember(db, "Ana's stores batch payouts on Fridays.", "run:run_a:recall:1", ana.org_id)
    console = _remember(db, "Fees under $1 are rounding.", "console", None)
    stray = _remember(db, "Written before items had an org.", "run:run_x:recall:1", None)
    listed = {m["id"]: m for m in ana.get("/v1/memory").json()}
    assert set(listed) == seeds | {own, console}
    assert listed[own]["source"] == "Run run_a" and listed[own]["sourceRun"] == "run_a"
    assert listed[console]["source"] == "New Machines"
    assert {m["id"] for m in ben.get("/v1/memory").json()} == seeds | {console}
    assert stray not in listed
    assert all(m["id"] not in {"mem_001"} for m in listed.values())  # no fixtures


def test_retracting_an_orgs_item_stops_runs_recalling_it(ana, ben, db):
    own = _remember(db, "Ana's stores batch payouts on Fridays.", "run:run_a:recall:1", ana.org_id)
    assert ben.post(f"/v1/memory/{own}:retract").status_code == 404  # another org's item
    res = ana.post(f"/v1/memory/{own}:retract")
    assert res.status_code == 200 and res.json()["retracted"] is True
    assert ana.post(f"/v1/memory/{own}:retract").status_code == 200  # idempotent
    [row] = _rows(db, "SELECT status, retracted_by FROM memory_items WHERE id = %s", own)
    assert row == {"status": "retracted", "retracted_by": "uid_ana"}
    assert next(m for m in ana.get("/v1/memory").json() if m["id"] == own)["retracted"] is True
    recalled = memory.recall(db, "retail-commerce", "payouts Fridays", limit=50, org_id=ana.org_id)
    assert own not in {i["id"] for i in recalled}
    assert _rows(db, "SELECT count(*) AS n FROM receipt_entries")[0]["n"] == 0  # receipt-free


def test_shared_items_cannot_be_retracted_from_one_org(ana, db):
    [seed] = _rows(db, "SELECT id FROM memory_items WHERE source = 'seed' LIMIT 1")
    res = ana.post(f"/v1/memory/{seed['id']}:retract")
    assert res.status_code == 403
    assert _rows(db, "SELECT status FROM memory_items WHERE id = %s", seed["id"])[0]["status"] == "active"
    assert (
        ana.post(f"/v1/memory-candidates/{seed['id']}:review", json={"decision": "approve"}).status_code
        == 409
    )
    assert ana.post("/v1/memory-candidates/mem_001:review", json={"decision": "approve"}).status_code == 404


def test_recall_without_an_org_fails_closed_to_shared_items(db, starts):
    own = _remember(db, "Org A refunds post a day late.", "run:run_a:n:1", "org_a")
    recalled = {i["id"] for i in memory.recall(db, "retail-commerce", "refunds late", limit=50)}
    assert recalled and own not in recalled
    shared = _rows(db, "SELECT id FROM memory_items WHERE org_id IS NULL AND source = 'seed'")
    assert recalled <= {r["id"] for r in shared}


def test_runs_recall_and_remember_within_their_org(db, starts):
    a = _remember(db, "Org A refunds post a day late.", "run:run_a:n:1", "org_a")
    b = _remember(db, "Org B refunds post a day late.", "run:run_b:n:1", "org_b")
    recalled = {
        i["id"] for i in memory.recall(db, "retail-commerce", "refunds late", limit=50, org_id="org_a")
    }
    assert a in recalled and b not in recalled
    call = activities.NodeCall(run_id="run_a", snapshot={"org_id": "org_a"}, node_id="learn", state={})
    node = {
        "id": "learn",
        "type": "memory",
        "config": {"op": "remember", "space": "retail-commerce", "text": "Hi"},
    }
    step = activities._memory(call, {**node, "routes": {"next": "x"}})
    step.write(db)
    db.commit()
    [row] = _rows(db, "SELECT org_id FROM memory_items WHERE source = 'run:run_a:learn:1'")
    assert row["org_id"] == "org_a"


def test_migration_003_gives_old_run_items_their_org_and_quarantines_the_rest(db):
    try:
        db.execute(
            "ALTER TABLE memory_items DROP COLUMN status, DROP COLUMN retracted_by, DROP COLUMN retracted_at"
        )
        db.execute("ALTER TABLE installations DROP CONSTRAINT installations_reviewer_pool_check")
        db.execute("ALTER TABLE connections DROP CONSTRAINT connections_status_check")
        db.execute("DELETE FROM schema_migrations WHERE name = '003_live_catalog.sql'")
        db.execute(
            "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input) "
            "VALUES ('run_7', 'org_a', 'p', 'COMPLETED', '{}', '{}', '{}')"
        )
        items = [
            ("m_run", "run:run_7:learn:1"),
            ("m_lost", "run:run_gone:learn:1"),
            ("m_other", "import"),
            ("m_seed", "seed"),
            ("m_console", "console"),
        ]
        for item_id, source in items:
            db.execute(
                "INSERT INTO memory_items (id, space, text, source, created_by) "
                "VALUES (%s, 's', 't', %s, 'x')",
                (item_id, source),
            )
        db.commit()
        assert app_db.migrate(db) == ["003_live_catalog.sql"]
        rows = {
            r["id"]: (r["org_id"], r["status"])
            for r in _rows(db, "SELECT id, org_id, status FROM memory_items")
        }
        assert rows == {
            "m_run": ("org_a", "active"),
            "m_lost": (None, "quarantined"),
            "m_other": (None, "quarantined"),
            "m_seed": (None, "active"),
            "m_console": (None, "active"),
        }
    finally:  # whatever failed above, `nm_test` keeps 008's pools and 011's statuses for the tests after it
        db.rollback()
        app_db.migrate(db)  # 003 re-adds its own pool and status checks: put 008's and 011's back
        db.execute("ALTER TABLE installations DROP CONSTRAINT IF EXISTS installations_reviewer_pool_check")
        db.execute(
            "ALTER TABLE installations ADD CONSTRAINT installations_reviewer_pool_check "
            "CHECK (reviewer_pool IN ('team', 'network', 'team_then_network'))"
        )
        db.execute("ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_status_check")
        db.execute(
            "ALTER TABLE connections ADD CONSTRAINT connections_status_check "
            "CHECK (status IN ('connected','not_connected','sandbox','needs_reauth','pending'))"
        )
        db.commit()


# --- earnings -------------------------------------------------------------------------------------------


def test_earnings_are_the_tasks_the_reviewer_decided(ana, ben, db):
    assert ana.get("/v1/reviewer/earnings").json() == []  # no fixtures
    _add_run(db, ana.org_id, "run_a")
    decided = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    tasks = [
        ("ht_paid", {"title": "Resolve mismatches", "pay": 750}, {"verdict": "REVISION_REQUIRED"}, "uid_ana"),
        ("ht_free", {"title": "Check totals"}, {"outcome": "rejected"}, "uid_ana"),
        ("ht_ben", {"title": "Someone else's"}, {"verdict": "APPROVED"}, "uid_ben"),
    ]
    for task_id, payload, result, by in tasks:
        status = "rejected" if result.get("outcome") == "rejected" else "resolved"
        db.execute(
            "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload, result, decided_by, "
            "decided_at) VALUES (%s, 'run_a', 'review', 'human', %s, %s, %s, %s, %s)",
            (task_id, status, Jsonb(payload), Jsonb(result), by, decided),
        )
    db.commit()
    earned = ana.get("/v1/reviewer/earnings").json()
    # Team reviews of the org's own tasks are unpaid, whatever pay the task names.
    assert [(e["taskId"], e["amount"]["amountMinor"], e["verdict"], e["via"]) for e in earned] == [
        ("ht_paid", 0, "REVISION_REQUIRED", "team"),
        ("ht_free", 0, "REJECTED", "team"),
    ]
    assert all(e["status"] == "PAID_SIMULATED" and e["simulated"] is True for e in earned)
    assert ben.get("/v1/reviewer/earnings").json() == []  # Ben's decision was in Ana's org
    json.dumps(earned)
