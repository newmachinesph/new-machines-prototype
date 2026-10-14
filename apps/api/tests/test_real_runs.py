"""The customer API on the real runtime (NM_RUNTIME=temporal): Postgres + the real definitions bundle.

Temporal is not needed: `app.temporal_client` is replaced with recorders.
"""

import threading
import time
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from app import real_runs, run_tasks, settings, temporal_client
from app.auth import Actor, get_actor
from app.defs import registry
from app.defs.loader import load_bundle
from app.errors import ApiProblem
from app.main import create_app
from app.store import get_store, reset_store
from app.worker import activities

PACK = "order-payment-reconciliation"
START = {"packSlug": PACK, "input": "2026-10-06..2026-10-12", "budgetMinor": 2000}
SEED_MEMORY = 10  # seed items of the retail-commerce (4) and customer-accounts (6) memory spaces
MISMATCHES = [
    {
        "order_id": "#1004",
        "charge_id": None,
        "kind": "missing_payment",
        "date": "2026-10-08",
        "amount_minor": 12900,
        "amount_diff_minor": -12900,
        "currency": "USD",
        "explanation": "No charge was found for this order.",
    },
    {
        "order_id": "#1007",
        "charge_id": "ch_7",
        "kind": "amount_mismatch",
        "date": "2026-10-09",
        "amount_minor": 8450,
        "amount_diff_minor": -275,
        "currency": "USD",
        "explanation": "The charge is short by the card fee.",
    },
]


class Recorder:
    """Stands in for app.temporal_client. `error` (when set) is raised by every call except terminate_run;
    `gate` (when set) makes start_run wait until it is released."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.gate: threading.Event | None = None

    def _record(self, *call) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append(call)

    def terminate_run(self, run_id, reason) -> None:
        self.calls.append(("terminate", run_id))

    def start_run(self, run_id, snapshot, input) -> None:
        if self.gate is not None:
            assert self.gate.wait(timeout=10)
        self._record("start", run_id, snapshot, input)

    def signal_human(self, run_id, task_id, outcome, note, resolutions=None) -> None:
        self._record("human", run_id, task_id, outcome, note, resolutions)

    def signal_approval(self, run_id, task_id, decision, by) -> None:
        self._record("approval", run_id, task_id, decision, by)


@pytest.fixture
def rec(db, monkeypatch) -> Recorder:
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    recorder = Recorder()
    for name in ("start_run", "signal_human", "signal_approval", "terminate_run"):
        monkeypatch.setattr(temporal_client, name, getattr(recorder, name))
    return recorder


@pytest.fixture
def api(rec) -> TestClient:
    reset_store()
    return TestClient(create_app())


def _rows(db, query: str, *args) -> list[dict]:
    db.commit()
    return db.execute(query, args).fetchall()


def _start(api) -> dict:
    res = api.post("/v1/workflow-runs", json=START)
    assert res.status_code == 202, res.text
    return res.json()


def _add_task(db, run_id: str, kind: str, payload: dict) -> str:
    node = "review" if kind == "human" else "approve_write"
    task_id = f"{'ht' if kind == 'human' else 'apr'}_{run_id}_{node}_1"
    status = "open" if kind == "human" else "pending"
    db.execute(
        "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) VALUES (%s, %s, %s, %s, %s, %s)",
        (task_id, run_id, node, kind, status, Jsonb(payload)),
    )
    db.commit()
    return task_id


HUMAN_PAYLOAD = {
    "title": "Resolve order and payment mismatches",
    "node_type": "human_workforce",
    "timeout_s": 86400,
    "expires_at": "2026-10-14T10:00:00Z",
    "instructions": "For each mismatch, decide whether it is explained.",
    "show": MISMATCHES,
}
APPROVAL_PAYLOAD = {
    "title": "Write the reconciliation report to the Sheet",
    "node_type": "approval",
    "timeout_s": 86400,
    "expires_at": "2026-10-14T10:00:00Z",
    "summary": "12 orders reconciled, 2 mismatches resolved by a reviewer.",
    "target_node": "write",
    "tool_ref": "googlesheets.append_rows",
    "policy_ref": "policy/default",
}


# --- start ----------------------------------------------------------------------------------------------


def test_start_pins_a_snapshot_inserts_the_run_and_starts_the_workflow(api, rec, db):
    run = _start(api)
    assert run["id"] == "run_2001"
    assert run["status"] == "RUNNING" and run["packSlug"] == PACK
    workflow = registry.latest(db, "workflow", PACK).body
    assert [n["id"] for n in run["nodes"]] == [n["id"] for n in workflow["nodes"]]
    assert run["budget"] == {"amountMinor": 2000, "currency": "USD"}
    assert _rows(db, "SELECT id FROM run_tasks") == []

    [(kind, run_id, snapshot, input)] = rec.calls
    assert (kind, run_id) == ("start", "run_2001")
    assert input == {"since": "2026-10-06", "until": "2026-10-12"}
    pinned = {(v["kind"], v["key"]): v["version"] for v in snapshot["versions"]}
    assert pinned[("pack", PACK)] == 1 and pinned[("contract", PACK)] == 1
    assert snapshot["org_id"] == "org_hp01" and snapshot["budget_minor"] == 2000
    assert snapshot["overrides"]["googlesheets"]["write"] == "require_approval"
    assert snapshot["overrides"]["stripe"]["money"] == "require_approval"
    assert set(snapshot["overrides"]) == {"shopify", "stripe", "googlesheets"}
    assert snapshot["disabled"] == []

    [row] = _rows(db, "SELECT org_id, status, input, snapshot FROM runs")
    assert row["org_id"] == "org_hp01" and row["status"] == "RUNNING"
    assert row["input"] == input and row["snapshot"]["versions"] == snapshot["versions"]
    [entry] = _rows(db, "SELECT type, data FROM receipt_entries WHERE run_id = 'run_2001'")
    assert entry["type"] == "run.started" and entry["data"]["versions"] == snapshot["versions"]


def test_a_connector_ops_disabled_is_disabled_in_the_snapshot(api, rec):
    entry = get_store().connector_catalog["shopify"]
    get_store().connector_catalog["shopify"] = entry.model_copy(update={"status": "disabled"})
    _start(api)
    assert rec.calls[0][2]["disabled"] == ["shopify"]


def test_run_ids_count_up(api):
    assert [_start(api)["id"] for _ in range(2)] == ["run_2001", "run_2002"]


def test_paused_platform_refuses_a_real_run(api, rec):
    get_store().guardrails["pause_all_runs"].enabled = True
    res = api.post("/v1/workflow-runs", json=START)
    assert res.status_code == 409 and res.json()["code"] == "PLATFORM_PAUSED"
    assert rec.calls == []


def test_budget_over_the_contract_maximum_is_refused(api, rec):
    res = api.post("/v1/workflow-runs", json={**START, "budgetMinor": 2501})
    assert res.status_code == 422 and res.json()["code"] == "BUDGET_TOO_HIGH"
    assert "$25.00" in res.json()["detail"]
    assert api.post("/v1/workflow-runs", json={**START, "budgetMinor": 999999}).status_code == 422
    assert rec.calls == []


def test_a_pack_not_hired_is_refused(api, rec):
    next(p for p in get_store().packs if p.slug == PACK).installed = False
    res = api.post("/v1/workflow-runs", json=START)
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"
    assert rec.calls == []


def test_a_pack_without_a_definition_keeps_the_fixture_path(api, rec):
    res = api.post(
        "/v1/workflow-runs",
        json={"packSlug": "weekly-inventory-report", "input": "last week", "budgetMinor": 500},
    )
    assert res.status_code == 202 and res.json()["id"] == "run_1048"
    assert rec.calls == []


def test_a_failed_workflow_start_fails_the_run(api, rec, db):
    rec.error = RuntimeError("temporal is down")
    res = api.post("/v1/workflow-runs", json=START)
    assert res.status_code == 503 and res.json()["code"] == "RUNTIME_UNAVAILABLE"
    [row] = _rows(db, "SELECT status, projection FROM runs")
    assert row["status"] == "FAILED" and row["projection"]["status"] == "FAILED"
    receipt = api.get("/v1/workflow-runs/run_2001/receipt").json()
    assert receipt["verified"] is True
    assert [i["type"] for i in receipt["items"]] == ["run.started", "run.failed", "receipt.sealed"]
    assert ("terminate", "run_2001") in rec.calls


def test_a_start_that_times_out_is_terminated_and_its_run_sealed_failed(api, rec, db):
    rec.error = TimeoutError()
    res = api.post("/v1/workflow-runs", json=START)
    assert res.status_code == 503 and res.json()["code"] == "RUNTIME_UNAVAILABLE"
    assert rec.calls == [("terminate", "run_2001")]
    [row] = _rows(db, "SELECT status FROM runs")
    assert row["status"] == "FAILED"
    types = [r["type"] for r in _rows(db, "SELECT type FROM receipt_entries ORDER BY seq")]
    assert types[-1] == "receipt.sealed"


def test_a_sealed_run_refuses_new_receipt_entries(api, rec, db):
    """A workflow started after the API gave up finds its run sealed; its first activity fails for good."""
    rec.error = TimeoutError()
    api.post("/v1/workflow-runs", json=START)
    db.commit()
    with pytest.raises(ApplicationError) as err:
        activities.record_events(db, "run_2001", [("start:1:node.started:1", "node.started", "start", {})])
    db.rollback()
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
    # A retry that only repeats recorded keys adds nothing and is not refused.
    assert activities.record_events(db, "run_2001", [("run:0:run.failed:0", "run.failed", None, {})]) == 0
    db.rollback()


def test_start_failure_is_documented_as_503():
    spec = create_app().openapi()
    responses = spec["paths"]["/v1/workflow-runs"]["post"]["responses"]
    assert "application/problem+json" in responses["503"]["content"]


# --- idempotency ----------------------------------------------------------------------------------------


def _post_in_thread(body: dict, key: str, out: list) -> threading.Thread:
    def run() -> None:
        res = TestClient(create_app()).post("/v1/workflow-runs", json=body, headers={"Idempotency-Key": key})
        out.append(res)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def test_a_slow_start_does_not_block_other_requests_and_its_key_runs_once(api, rec):
    rec.gate = threading.Event()
    results: list = []
    first = _post_in_thread(START, "k-1", results)
    time.sleep(0.5)  # the first request is now waiting inside start_run
    second = _post_in_thread(START, "k-1", results)
    began = time.monotonic()
    assert api.get("/v1/workflow-packs").status_code == 200
    assert api.get("/v1/approvals").status_code == 200
    assert time.monotonic() - began < 2  # the store lock is free while the start waits
    rec.gate.set()
    first.join(timeout=20)
    second.join(timeout=20)
    assert [r.status_code for r in results] == [202, 202]
    assert results[0].json()["id"] == results[1].json()["id"] == "run_2001"
    assert len([c for c in rec.calls if c[0] == "start"]) == 1
    again = api.post("/v1/workflow-runs", json=START, headers={"Idempotency-Key": "k-1"})
    assert again.json()["id"] == "run_2001"
    changed = {**START, "budgetMinor": 1500}
    assert api.post("/v1/workflow-runs", json=changed, headers={"Idempotency-Key": "k-1"}).status_code == 409
    assert get_store().idempotency_locks == {}


def test_a_failed_start_is_not_cached_for_its_key(api, rec):
    rec.error = RuntimeError("temporal is down")
    headers = {"Idempotency-Key": "k-2"}
    assert api.post("/v1/workflow-runs", json=START, headers=headers).status_code == 503
    rec.error = None
    res = api.post("/v1/workflow-runs", json=START, headers=headers)
    assert res.status_code == 202 and res.json()["id"] == "run_2002"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01..2026-10-05", ("2026-10-01", "2026-10-05")),
        ("from 2026-10-01 .. 2026-10-05 please", ("2026-10-01", "2026-10-05")),
        ("last 30 days", ("2026-09-14", "2026-10-13")),
        ("Reconcile the last 3 days of orders", ("2026-10-11", "2026-10-13")),
        ("last week", ("2026-10-07", "2026-10-13")),
        ("this week's payouts", ("2026-10-07", "2026-10-13")),
    ],
)
def test_free_text_input_becomes_a_date_range(text, expected):
    got = real_runs.parse_run_input(text, today=date(2026, 10, 13))
    assert (got["since"], got["until"]) == expected


@pytest.mark.parametrize("text", ["2026-10-05..2026-10-01", "2026-13-01..2026-13-05", "last 0 days"])
def test_bad_date_input_is_refused(text):
    with pytest.raises(ApiProblem) as err:
        real_runs.parse_run_input(text, today=date(2026, 10, 13))
    assert err.value.status == 422 and err.value.code == "INVALID_INPUT"


def _pack_input_schema(pack: str) -> dict:
    bundle = load_bundle(settings.defs_dir())
    return bundle.get("schema", f"{pack}/input").body


OVERDUE = "overdue-invoice-follow-up"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01", "2026-10-01"),
        ("as of 2026-09-30 please", "2026-09-30"),
        ("today", "2026-10-13"),
        ("Chase what is late today", "2026-10-13"),
        ("", "2026-10-13"),
        ("   ", "2026-10-13"),
    ],
)
def test_free_text_for_a_one_date_pack_becomes_that_date(text, expected):
    schema = _pack_input_schema(OVERDUE)
    assert real_runs.single_date_field(schema) == "as_of"
    assert real_runs.parse_run_input(text, today=date(2026, 10, 13), schema=schema) == {"as_of": expected}


@pytest.mark.parametrize("text", ["next week", "2026-13-01"])
def test_free_text_for_a_one_date_pack_without_a_day_is_refused(text):
    with pytest.raises(ApiProblem) as err:
        real_runs.parse_run_input(text, today=date(2026, 10, 13), schema=_pack_input_schema(OVERDUE))
    assert err.value.status == 422 and err.value.code == "INVALID_INPUT"


def test_free_text_keeps_the_date_range_for_other_schemas():
    for pack in (PACK, "refund-triage"):
        schema = _pack_input_schema(pack)
        assert real_runs.single_date_field(schema) is None
        got = real_runs.parse_run_input("last 3 days", today=date(2026, 10, 13), schema=schema)
        assert got == {"since": "2026-10-11", "until": "2026-10-13"}
    one_optional = {"type": "object", "properties": {"day": {"type": "string", "format": "date"}}}
    assert real_runs.single_date_field(one_optional) is None
    one_text = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    assert real_runs.single_date_field(one_text) is None
    assert real_runs.single_date_field(
        {"required": ["d"], "properties": {"d": {"type": "string", "format": "date"}}}
    )


def test_free_text_for_the_overdue_pack_passes_its_input_schema():
    assert real_runs.check_input(OVERDUE, "2026-10-13", _pack_input_schema(OVERDUE)) == {
        "as_of": "2026-10-13"
    }


def test_a_free_text_start_of_the_overdue_pack_runs_for_real(api, rec):
    """A start that sends free text (a pack page without the form's fields) must not fail with 422."""
    res = api.post(
        "/v1/workflow-runs", json={"packSlug": OVERDUE, "input": "2026-10-13", "budgetMinor": 1000}
    )
    assert res.status_code == 202, res.text
    [(kind, _, _, input)] = rec.calls
    assert (kind, input) == ("start", {"as_of": "2026-10-13"})


def test_every_real_pack_detail_carries_its_input_schema(api):
    for pack, required in (
        (PACK, ["since", "until"]),
        (OVERDUE, ["as_of"]),
        ("refund-triage", ["since", "until"]),
    ):
        detail = api.get(f"/v1/workflow-packs/{pack}").json()
        assert detail["inputSchema"]["required"] == required, pack
    assert "inputSchema" not in api.get("/v1/workflow-packs/weekly-inventory-report").json()


def test_a_database_error_loading_the_input_schema_still_serves_the_detail(api, monkeypatch, caplog):
    def down(*_args):
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(real_runs, "input_schema", down)
    res = api.get(f"/v1/workflow-packs/{OVERDUE}")
    assert res.status_code == 200 and res.json()["slug"] == OVERDUE
    assert "inputSchema" not in res.json()
    assert any("Could not load the input schema" in r.getMessage() for r in caplog.records)


def test_a_pack_detail_has_no_input_schema_when_the_runtime_is_off(client):
    assert "inputSchema" not in client.get(f"/v1/workflow-packs/{OVERDUE}").json()


# --- read -----------------------------------------------------------------------------------------------


def test_list_puts_real_runs_first_and_get_serves_the_projection(api):
    run = _start(api)
    listed = api.get("/v1/workflow-runs").json()
    assert listed[0]["id"] == run["id"] and listed[0]["hasDetail"] is True
    assert len(listed) == len(get_store().run_summaries) + 1
    got = api.get(f"/v1/workflow-runs/{run['id']}")
    assert got.status_code == 200 and got.json()["nodes"] == run["nodes"]
    assert api.get("/v1/workflow-runs/run_1047").status_code == 200  # fixtures still served


def test_a_malformed_projection_is_left_out_of_the_list(api, db):
    good, bad = _start(api), _start(api)
    db.execute("UPDATE runs SET projection = %s WHERE id = %s", (Jsonb({"bad": 1}), bad["id"]))
    db.commit()
    res = api.get("/v1/workflow-runs")
    assert res.status_code == 200
    ids = [r["id"] for r in res.json()]
    assert good["id"] in ids and bad["id"] not in ids


def test_another_org_cannot_see_or_decide_real_runs_and_tasks(api, rec, db):
    run = _start(api)
    approval = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    task = _add_task(db, run["id"], "human", HUMAN_PAYLOAD)
    api.app.dependency_overrides[get_actor] = lambda: Actor(user_id="user_other", org_id="org_other")
    assert api.get(f"/v1/workflow-runs/{run['id']}").status_code == 404
    assert api.get(f"/v1/workflow-runs/{run['id']}/receipt").status_code == 404
    assert api.post(f"/v1/approvals/{approval}:approve").status_code == 404
    assert api.post(f"/v1/human-tasks/{task}:claim").status_code == 404
    assert api.get(f"/v1/human-tasks/{task}").status_code == 404
    assert all(r["id"] != run["id"] for r in api.get("/v1/workflow-runs").json())
    assert all(a["id"] != approval for a in api.get("/v1/approvals").json())
    assert [c for c in rec.calls if c[0] != "start"] == []
    [row] = _rows(db, "SELECT status FROM run_tasks WHERE id = %s", approval)
    assert row["status"] == "pending"


def test_receipt_verifies_and_lists_pinned_versions(api):
    run = _start(api)
    receipt = api.get(f"/v1/workflow-runs/{run['id']}/receipt").json()
    assert receipt["runId"] == run["id"]
    assert receipt["verified"] is True and receipt["entries"] == 1
    assert receipt["headHash"].startswith("sha256:")
    [pack] = [p for p in receipt["pinned"] if p["kind"] == "pack"]
    assert pack["key"] == PACK and pack["version"] == 1 and pack["digest"].startswith("sha256:")
    [item] = receipt["items"]
    assert item["seq"] == 1 and item["type"] == "run.started" and item["hash"] == receipt["headHash"]
    assert item["summary"]


def test_receipt_is_404_for_fixture_and_unknown_runs(api):
    assert api.get("/v1/workflow-runs/run_1047/receipt").status_code == 404
    assert api.get("/v1/workflow-runs/run_9999/receipt").status_code == 404


# --- approvals ------------------------------------------------------------------------------------------


def test_a_real_approval_is_listed_first_and_approving_signals_the_workflow(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    listed = api.get("/v1/approvals").json()
    first = listed[0]
    assert first["id"] == task_id and first["runId"] == run["id"] and first["status"] == "PENDING"
    assert first["title"] == APPROVAL_PAYLOAD["title"]
    assert first["summary"] == APPROVAL_PAYLOAD["summary"]
    # A real approval is the step it lets the run take, not an email.
    assert "preview" not in first
    assert first["action"] == {
        "app": "Google Sheets",
        "step": "write",
        "tool": "googlesheets.append_rows",
        "operation": "append rows",
        "summary": APPROVAL_PAYLOAD["summary"],
        "mocked": False,
    }
    assert [d["label"] for d in first["digest"]] == ["Run", "Policy"]
    assert first["expiresAt"] == "2026-10-14T10:00:00Z" and first["policyRef"] == "policy/default"
    assert len(listed) == len(get_store().approvals) + 1

    res = api.post(f"/v1/approvals/{task_id}:approve")
    assert res.status_code == 200 and res.json()["status"] == "GRANTED"
    assert rec.calls[-1] == ("approval", run["id"], task_id, "granted", "user_demo")
    [row] = _rows(db, "SELECT status, decided_by, decided_at, result FROM run_tasks")
    assert row["status"] == "granted" and row["decided_by"] == "user_demo" and row["decided_at"]
    assert row["result"]["decision"] == "granted"

    # The same person approving again re-sends the signal (a lost one is recoverable); declining is a 409.
    again = api.post(f"/v1/approvals/{task_id}:approve")
    assert again.status_code == 200 and again.json()["status"] == "GRANTED"
    assert api.post(f"/v1/approvals/{task_id}:decline").status_code == 409
    signals = [c for c in rec.calls if c[0] == "approval"]
    assert signals == [("approval", run["id"], task_id, "granted", "user_demo")] * 2


def test_another_person_cannot_repeat_a_decided_approval(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    assert api.post(f"/v1/approvals/{task_id}:approve").status_code == 200
    db.execute("UPDATE run_tasks SET decided_by = 'someone_else' WHERE id = %s", (task_id,))
    db.commit()
    assert api.post(f"/v1/approvals/{task_id}:approve").status_code == 409
    assert len([c for c in rec.calls if c[0] == "approval"]) == 1


def test_a_signal_to_a_missing_workflow_fails_the_run(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    rec.error = RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
    res = api.post(f"/v1/approvals/{task_id}:approve")
    assert res.status_code == 200 and res.json()["status"] == "GRANTED"
    [row] = _rows(db, "SELECT status, projection FROM runs WHERE id = %s", run["id"])
    assert row["status"] == "FAILED" and row["projection"]["status"] == "FAILED"
    entries = _rows(db, "SELECT type, data FROM receipt_entries WHERE run_id = %s ORDER BY seq", run["id"])
    assert [e["type"] for e in entries][-2:] == ["run.failed", "receipt.sealed"]
    assert entries[-2]["data"]["reason"] == run_tasks.LOST_REASON
    run_tasks.fail_lost_run(run["id"])  # a second report about a finished run changes nothing
    assert len(_rows(db, "SELECT seq FROM receipt_entries WHERE run_id = %s", run["id"])) == len(entries)


def test_a_missing_namespace_does_not_fail_the_run(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    rec.error = RPCError("Namespace nm-prod is not found.", RPCStatusCode.NOT_FOUND, b"")
    assert api.post(f"/v1/approvals/{task_id}:approve").status_code == 200
    [row] = _rows(db, "SELECT status FROM runs WHERE id = %s", run["id"])
    assert row["status"] != "FAILED"


def test_an_unreachable_temporal_does_not_fail_the_run(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    rec.error = RPCError("connection refused", RPCStatusCode.UNAVAILABLE, b"")
    assert api.post(f"/v1/approvals/{task_id}:approve").status_code == 200
    [row] = _rows(db, "SELECT status FROM runs WHERE id = %s", run["id"])
    assert row["status"] != "FAILED"


def test_declining_a_real_approval_signals_denied(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    res = api.post(f"/v1/approvals/{task_id}:decline")
    assert res.status_code == 200 and res.json()["status"] == "DECLINED"
    assert rec.calls[-1] == ("approval", run["id"], task_id, "denied", "user_demo")


def test_a_failed_signal_keeps_the_recorded_decision(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "approval", APPROVAL_PAYLOAD)
    rec.error = RuntimeError("temporal is down")
    res = api.post(f"/v1/approvals/{task_id}:approve")
    assert res.status_code == 200 and res.json()["status"] == "GRANTED"
    [row] = _rows(db, "SELECT status FROM run_tasks")
    assert row["status"] == "granted"


def test_a_real_approval_says_when_its_step_would_run_on_sandbox_data(api, rec, db):
    run = _start(api)
    _add_task(db, run["id"], "approval", {**APPROVAL_PAYLOAD, "mocked": True})
    first = api.get("/v1/approvals").json()[0]
    assert first["action"]["mocked"] is True


def test_fixture_approvals_keep_their_email_preview(api):
    fixture_ids = {a.id for a in get_store().approvals}
    fixtures = [a for a in api.get("/v1/approvals").json() if a["id"] in fixture_ids]
    assert fixtures and all(a["preview"]["to"] and "action" not in a for a in fixtures)


def test_fixture_approvals_still_work_with_the_runtime_on(api, rec):
    fixture = next(a for a in get_store().approvals if a.status == "PENDING")
    res = api.post(f"/v1/approvals/{fixture.id}:approve")
    assert res.status_code == 200 and res.json()["status"] == "GRANTED"
    assert rec.calls == []


# --- human tasks ----------------------------------------------------------------------------------------


def test_a_real_human_task_is_offered_claimed_and_submitted(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "human", HUMAN_PAYLOAD)

    eligible = api.get("/v1/human-tasks/eligible").json()
    offer = next(t for t in eligible if t["id"] == task_id)
    assert eligible[0]["id"] == task_id
    assert offer["state"] == "OFFERED" and offer["records"] == [] and offer["runId"] == run["id"]

    task = api.get(f"/v1/human-tasks/{task_id}").json()
    assert task["title"] == HUMAN_PAYLOAD["title"] and task["instructions"] == HUMAN_PAYLOAD["instructions"]
    assert [r["id"] for r in task["records"]] == ["#1004", "#1007"]
    assert task["records"][1]["flag"] == "Amount mismatch"
    assert task["records"][1]["agentNote"] == "The charge is short by the card fee."
    assert task["deadline"] == "2026-10-14T10:00:00Z" and task["packName"] == run["title"]
    assert task["realRun"] is True and "runOutcome" not in task
    assert task["payTerms"] == "Demo run: no reviewer pay" and "via" not in task  # the demo copy, unrouted

    review = {"verdict": "APPROVED", "feedbackText": "Both explained.", "recordCalls": {"#1004": "timing"}}
    assert api.post(f"/v1/human-tasks/{task_id}:submit", json=review).status_code == 409

    claimed = api.post(f"/v1/human-tasks/{task_id}:claim")
    assert claimed.status_code == 200 and claimed.json()["state"] == "CLAIMED"
    assert all(t["id"] != task_id for t in api.get("/v1/human-tasks/eligible").json())

    res = api.post(f"/v1/human-tasks/{task_id}:submit", json=review)
    assert res.status_code == 200 and res.json()["state"] == "SUBMITTED"
    assert res.json()["runOutcome"] == "CONTINUES"
    assert api.get(f"/v1/human-tasks/{task_id}").json()["runOutcome"] == "CONTINUES"
    resolutions = [{"order_id": "#1004", "resolution": "timing", "note": ""}]
    assert rec.calls[-1] == ("human", run["id"], task_id, "resolved", "Both explained.", resolutions)
    [row] = _rows(db, "SELECT status, decided_by, decided_at, result FROM run_tasks")
    assert row["status"] == "resolved" and row["decided_by"] == "user_demo" and row["decided_at"]
    assert row["result"] == {
        "outcome": "resolved",
        "note": "Both explained.",
        "resolutions": resolutions,
        "verdict": "APPROVED",
    }

    # Submitting the same outcome again re-signals the recorded review (not the new text); another is a 409.
    resend = {**review, "feedbackText": "Changed my mind about the wording.", "recordCalls": {}}
    assert api.post(f"/v1/human-tasks/{task_id}:submit", json=resend).status_code == 200
    assert rec.calls[-1] == ("human", run["id"], task_id, "resolved", "Both explained.", resolutions)
    rejected = {**review, "verdict": "REJECTED"}
    assert api.post(f"/v1/human-tasks/{task_id}:submit", json=rejected).status_code == 409
    assert api.post(f"/v1/human-tasks/{task_id}:claim").status_code == 409
    assert len([c for c in rec.calls if c[0] == "human"]) == 2


@pytest.mark.parametrize(
    ("verdict", "outcome", "run_outcome"),
    [
        ("APPROVED", "resolved", "CONTINUES"),
        ("REVISION_REQUIRED", "resolved", "CONTINUES"),
        ("REJECTED", "rejected", "STOPS"),
        ("ESCALATED", "rejected", "STOPS"),
    ],
)
def test_review_verdicts_map_to_human_outcomes(api, rec, db, verdict, outcome, run_outcome):
    run = _start(api)
    task_id = _add_task(db, run["id"], "human", HUMAN_PAYLOAD)
    api.post(f"/v1/human-tasks/{task_id}:claim")
    review = {"verdict": verdict, "feedbackText": "Checked.", "recordCalls": {}}
    res = api.post(f"/v1/human-tasks/{task_id}:submit", json=review)
    assert res.status_code == 200 and res.json()["runOutcome"] == run_outcome
    assert rec.calls[-1][3] == outcome


def test_review_text_and_calls_are_capped_before_signalling(api, rec, db):
    run = _start(api)
    shown = [{**MISMATCHES[0], "order_id": f"#{i:04d}"} for i in range(150)]
    task_id = _add_task(db, run["id"], "human", {**HUMAN_PAYLOAD, "show": shown})
    api.post(f"/v1/human-tasks/{task_id}:claim")
    calls = {f"#{i:04d}": "x" * 1500 for i in range(150)}
    review = {"verdict": "APPROVED", "feedbackText": "n" * 4000, "recordCalls": calls}
    assert api.post(f"/v1/human-tasks/{task_id}:submit", json=review).status_code == 200
    _, _, _, _, note, resolutions = rec.calls[-1]
    assert len(note) == 1000 and len(resolutions) == 100
    assert all(len(r["resolution"]) == 1000 for r in resolutions)


def test_review_calls_for_records_the_task_never_showed_are_dropped(api, rec, db):
    run = _start(api)
    task_id = _add_task(db, run["id"], "human", HUMAN_PAYLOAD)
    api.post(f"/v1/human-tasks/{task_id}:claim")
    calls = {"#1007": "fee", "#9999": "made up", "<script>": "x"}
    review = {"verdict": "APPROVED", "feedbackText": "Checked.", "recordCalls": calls}
    assert api.post(f"/v1/human-tasks/{task_id}:submit", json=review).status_code == 200
    assert rec.calls[-1][5] == [{"order_id": "#1007", "resolution": "fee", "note": ""}]


def test_fixture_human_tasks_still_work_with_the_runtime_on(api, rec):
    fixture = next(t for t in get_store().tasks.values() if t.state == "OFFERED")
    assert api.post(f"/v1/human-tasks/{fixture.id}:claim").json()["state"] == "CLAIMED"
    assert rec.calls == []


# --- catalog and memory ---------------------------------------------------------------------------------


def test_taxonomy_comes_from_the_registry(api):
    taxonomy = api.get("/v1/catalog/taxonomy").json()
    assert len(taxonomy["functions"]) == 5 and len(taxonomy["industries"]) == 3
    assert taxonomy["functions"][0] == {"id": "finance-ops", "name": "Finance operations"}


def test_packs_carry_function_and_industries(api):
    pack = api.get(f"/v1/workflow-packs/{PACK}").json()
    assert pack["function"] == "finance-ops"
    assert pack["industries"] == ["retail-commerce", "manufacturing"]
    other = api.get("/v1/workflow-packs/weekly-inventory-report").json()
    assert other["industries"] == [] and "function" not in other
    listed = {p["slug"]: p for p in api.get("/v1/workflow-packs").json()}
    assert listed[PACK]["function"] == "finance-ops"


def test_memory_lists_real_items_first(api):
    items = api.get("/v1/memory").json()
    spaces = {"Retail & Commerce company knowledge", "Customer accounts policies"}
    real = [m for m in items if m["scopeName"] in spaces]
    assert len(real) == SEED_MEMORY and items[: len(real)] == real
    assert {m["scopeName"] for m in real} == spaces
    assert all(m["state"] == "APPROVED" and m["scope"] == "Organization" for m in real)
    assert len(items) == len(get_store().memory) + SEED_MEMORY


def test_demo_memory_leaves_out_other_orgs_and_quarantined_items(api, db):
    db.execute(
        "INSERT INTO memory_items (id, space, text, source, created_by, org_id, status) "
        "SELECT 'mem_other', space, 'Another org', 'run:run_x:n:1', 'run', 'org_other', 'active' "
        "FROM memory_items LIMIT 1"
    )
    db.execute(
        "INSERT INTO memory_items (id, space, text, source, created_by, org_id, status) "
        "SELECT 'mem_quarantined', space, 'Lost run', 'run:run_y:n:1', 'run', NULL, 'quarantined' "
        "FROM memory_items LIMIT 1"
    )
    db.commit()
    ids = {m["id"] for m in api.get("/v1/memory").json()}
    assert "mem_other" not in ids and "mem_quarantined" not in ids


# --- runtime off and startup ----------------------------------------------------------------------------


def test_taxonomy_reads_the_definition_files_when_the_runtime_is_off(client):
    taxonomy = client.get("/v1/catalog/taxonomy").json()
    assert len(taxonomy["functions"]) == 5 and len(taxonomy["industries"]) == 3
    assert client.get(f"/v1/workflow-packs/{PACK}").json()["function"] == "finance-ops"


def test_startup_migrates_and_applies_definitions_when_auto_apply_is_on(db, monkeypatch):
    monkeypatch.setenv("NM_DEFS_AUTO_APPLY", "1")
    assert _rows(db, "SELECT 1 FROM definition_versions") == []
    with TestClient(create_app()) as api:
        assert api.get("/healthz").status_code == 200
    assert _rows(db, "SELECT 1 FROM definition_versions WHERE kind = 'pack' AND key = %s", PACK)
    assert len(_rows(db, "SELECT 1 FROM memory_items")) == SEED_MEMORY
