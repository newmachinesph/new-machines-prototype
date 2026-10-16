"""Sub-project D end to end, over HTTP with mocked sign-in: Ana's workspace publishes a pack, ops approves it,
Ben's workspace sees it, adds it and runs it, pays the fee, and Ana earns her share. Nothing of Ana's draft or
review state reaches Ben. Then the runtime half: a listed agent's per-call fee, written by PackRunner."""

import asyncio
import copy
import json

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from app import fees
from app.defs import registry
from app.worker.workflow import PackRunner
from tests.publishing_seed import add_listing, add_version, approve_and_list, defs_of
from tests.team_seed import _own, clone_agent
from tests.test_live_catalog import INPUT, As
from tests.test_ops_state import OPS, ana, live, ops_post, starts  # noqa: F401
from tests.test_submissions import clone_pack
from tests.test_workflow import (  # noqa: F401  (fixture)
    _drive,
    _entries,
    _new_run,
    _start,
    _waiting,
    adk_plugins,
    runtime_env,
)

PACK = "order-payment-reconciliation"
APPS = ("shopify", "stripe", "googlesheets")
PUBLISHER = "org_acme_labs"
AGENT_FEE = 30
NOTES = ("Clear and tested", "Second look done")  # ops' decision notes: Ana's and ops' business only
DRAFT = "Acme recon, reworded"  # Ana's later draft, unsubmitted until step 6


def _submit(publisher: As, key: str, price: int) -> dict:
    res = publisher.post(
        f"/v1/organizations/{publisher.org_id}/studio/packs/{key}/submissions",
        json={"priceMinor": price, "input": INPUT},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _approve(live, db, submitted: dict, note: str) -> None:  # noqa: F811
    """The version's sandbox run completes (a reused completed test already has), the queue settles it into
    review, and ops approves it."""
    [sandbox] = [c["runId"] for c in submitted["latest"]["checks"] if c["name"] == "sandbox"]
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = %s", (sandbox,))
    db.commit()
    queue = live.get("/v1/ops/listings?status=in_review", headers=OPS).json()
    assert submitted["id"] in {r["id"] for r in queue}
    res = ops_post(live, f"/v1/ops/listings/{submitted['id']}:approve", reason=note)
    assert res.status_code == 200, res.text


def _run(ben: As, key: str) -> str:
    run = ben.post("/v1/workflow-runs", json={"packSlug": key, "input": INPUT, "budgetMinor": 1500})
    assert run.status_code == 202, run.text
    return run.json()["id"]


def _fee_rows(db, buyer: str) -> list[tuple]:
    db.commit()
    rows = db.execute(
        "SELECT run_id, kind, listing_version_id, amount_minor, publisher_share_minor FROM fee_lines "
        "WHERE buyer_org_id = %s ORDER BY id",
        (buyer,),
    ).fetchall()
    return [tuple(r.values()) for r in rows]


def _bens_reads(ben: As, key: str, run_ids: list[str]) -> list[str]:
    """Every response of Ben's that names Ana's pack: the marketplace, its detail, his receipts and Usage."""
    responses = [
        ben.get("/v1/workflow-packs"),
        ben.get(f"/v1/workflow-packs/{key}"),
        *(ben.get(f"/v1/workflow-runs/{run_id}/receipt") for run_id in run_ids),
        ben.get(f"/v1/organizations/{ben.org_id}/usage"),
    ]
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    return [r.text for r in responses]


def _review_state(submitted: dict) -> set[str]:
    """What only Ana and ops may read: listing version ids, sandbox check runs and details, and notes."""
    secret = set(NOTES)
    for version in submitted["versions"]:
        secret.add(version["id"])
        for check in version["checks"]:
            secret |= {check[field] for field in ("detail", "runId") if check.get(field)}
    assert any(s.startswith("run_") for s in secret)  # the sandbox check run is among them
    return secret


def test_submit_approve_and_use_in_another_workspace(live, ana, starts, db):  # noqa: F811
    ben = As(live, "ben")
    # 1. Ana turns publishing on and submits her pack at $2.50 a run.
    publisher = ana.api.put(
        f"/v1/organizations/{ana.org_id}/publisher", json={"name": "Acme Labs"}, headers=ana.headers
    )
    assert publisher.status_code == 200, publisher.text
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    db.commit()
    first = _submit(ana, key, 250)
    listing, v1 = first["id"], first["latest"]["id"]
    assert key not in {p["slug"] for p in ben.get("/v1/workflow-packs").json()}  # not before approval
    # 2. The sandbox run completes; the version reaches the queue; ops approves it.
    _approve(live, db, first, NOTES[0])
    # 3. Ben sees it with Ana's publisher name and fee, adds it, connects and runs it.
    seen = {p["slug"]: p for p in ben.get("/v1/workflow-packs").json()}[key]
    assert seen["publisher"] == "Acme Labs" and seen["listing"]["fee"]["amountMinor"] == 250
    body = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(f"/v1/organizations/{ben.org_id}/agent-installations", json=body).status_code == 201
    for app in APPS:
        assert ben.connect(app).status_code == 200
    run_id = _run(ben, key)
    # 4. The fee is charged at the approved version Ben holds, is on his receipt and Usage, and in Ana's
    # numbers; Ben never sees Ana's listing.
    assert _fee_rows(db, ben.org_id) == [(run_id, "pack_run", v1, 250, 200)]
    receipt = ben.get(f"/v1/workflow-runs/{run_id}/receipt").json()
    assert [f["amount"]["amountMinor"] for f in receipt["fees"]] == [250]
    usage = ben.get(f"/v1/organizations/{ben.org_id}/usage").json()
    assert any(line["account"] == "Publisher fees" for txn in usage["ledger"] for line in txn["lines"])
    mine = ana.get(f"/v1/organizations/{ana.org_id}/studio/listings").json()
    assert mine[0]["earningsMonth"]["amountMinor"] == 200 and mine[0]["runs30d"] == 1
    assert ben.get(f"/v1/organizations/{ben.org_id}/studio/listings/{listing}").status_code == 404
    assert fees.items(db, [run_id], ana.org_id) == {}
    # 5. Ana rewords her pack in the Studio (a draft, not submitted): Ben still sees the approved name, and
    # nothing of Ana's draft or review state is in anything he reads.
    _own(db, ana.org_id, "pack", key, {**registry.latest(db, "pack", key).body, "name": DRAFT})
    db.commit()
    assert {p["slug"]: p for p in ben.get("/v1/workflow-packs").json()}[key]["name"] == "Acme recon"
    assert ben.get(f"/v1/workflow-packs/{key}").json()["name"] == "Acme recon"
    secret = _review_state(first) | {DRAFT}
    leaks = [(s, t) for t in _bens_reads(ben, key, [run_id]) for s in secret if s in t]
    assert leaks == [], leaks
    # 6. Ana submits the reworded version at $4.00 and ops approves it. Ben has not updated: his next run is
    # charged $2.50 at the version he holds, and Ana earns $2.00 again.
    second = _submit(ana, key, 400)
    v2 = second["latest"]["id"]
    assert v2 != v1
    _approve(live, db, second, NOTES[1])
    assert {p["slug"]: p for p in ben.get("/v1/workflow-packs").json()}[key]["listing"]["updateAvailable"]
    again = _run(ben, key)
    assert _fee_rows(db, ben.org_id) == [
        (run_id, "pack_run", v1, 250, 200),
        (again, "pack_run", v1, 250, 200),
    ]
    receipt = ben.get(f"/v1/workflow-runs/{again}/receipt").json()
    assert [f["amount"]["amountMinor"] for f in receipt["fees"]] == [250]
    mine = ana.get(f"/v1/organizations/{ana.org_id}/studio/listings").json()
    assert mine[0]["earningsMonth"]["amountMinor"] == 400 and mine[0]["runs30d"] == 2
    secret = _review_state(second)
    leaks = [(s, t) for t in _bens_reads(ben, key, [run_id, again]) for s in secret if s in t]
    assert leaks == [], leaks
    # 7. Ben's runs finish and he updates: his next run is charged $4.00 at the version he now holds.
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE org_id = %s", (ben.org_id,))
    db.commit()
    upgraded = ben.post(f"/v1/organizations/{ben.org_id}/agent-installations/{key}:upgrade")
    assert upgraded.status_code == 200, upgraded.text
    third = _run(ben, key)
    # 8. Ana widens only the contract (the pack stays at its version 2) and it is approved at $5.00. The
    # buyer holds the listing version, not just the pack version: his next run is still charged $4.00 at v2.
    contract = registry.latest(db, "contract", key).body
    auth = contract["authorization"]
    wider = {**auth, "tool_capabilities": [*auth["tool_capabilities"], "invoices.read"]}
    _own(db, ana.org_id, "contract", key, {**contract, "authorization": wider})
    db.commit()
    rewidened = _submit(ana, key, 500)
    assert rewidened["latest"]["definitionVersion"] == 2  # the same pack version as v2
    _approve(live, db, rewidened, NOTES[1])
    assert {p["slug"]: p for p in ben.get("/v1/workflow-packs").json()}[key]["listing"]["updateAvailable"]
    fourth = _run(ben, key)
    assert _fee_rows(db, ben.org_id)[2:] == [
        (third, "pack_run", v2, 400, 320),
        (fourth, "pack_run", v2, 400, 320),
    ]
    mine = ana.get(f"/v1/organizations/{ana.org_id}/studio/listings").json()
    assert mine[0]["earningsMonth"]["amountMinor"] == 200 + 200 + 320 + 320 and mine[0]["runs30d"] == 4


def _listed_agent(db) -> tuple[str, str]:
    """A publisher's copy of the seed pack's matching agent, listed at its first version for AGENT_FEE a call:
    (agent key, approved listing version id)."""
    db.execute("INSERT INTO orgs (id, name) VALUES (%s, 'Acme Labs') ON CONFLICT DO NOTHING", (PUBLISHER,))
    # The buyer (`_new_run` runs as org_demo): its monthly cap bounds the fee, so its row must exist.
    db.execute("INSERT INTO orgs (id, name) VALUES ('org_demo', 'Demo Co') ON CONFLICT DO NOTHING")
    agent = clone_agent(db, "finance-agent", PUBLISHER, "matcher", title="Matcher")
    listing = add_listing(db, "agent", agent, PUBLISHER, name="Matcher")
    version = add_version(db, listing, 1, defs_of(db, [("agent", agent)]), price_minor=AGENT_FEE)
    approve_and_list(db, listing, version)
    db.commit()
    return agent, version


def _uses(conn, agent: str):
    """The run's `edit`: the pack's agent step calls the listed agent, pinned at its approved version, and the
    run's fee plan is what `real_runs` pins for it. The copy keeps the finance agent's prompt and `agent_id`,
    so the fake provider answers it as it answers the seed pack."""

    def edit(snapshot: dict) -> dict:
        snapshot = copy.deepcopy(snapshot)
        snapshot["defs"]["agent"][agent] = copy.deepcopy(snapshot["defs"]["agent"]["finance-agent"])
        snapshot["versions"].append({"kind": "agent", "key": agent, "version": 1, "digest": "listed"})
        workflow = snapshot["defs"]["workflow"][PACK]["body"]
        uses = [
            n for n in workflow["nodes"] if n["type"] == "agent" and n["config"]["agent"] == "finance-agent"
        ]
        assert [n["id"] for n in uses] == ["match"]  # the seed pack's one finance-agent step
        for node in uses:
            node["config"]["agent"] = agent
        snapshot["fees"] = fees.plan_fees(conn, snapshot, snapshot["org_id"])
        return snapshot

    return edit


def _fee_lines(conn, run_id: str) -> list[dict]:
    conn.commit()
    return conn.execute(
        "SELECT event_key, kind, listing_version_id, buyer_org_id, publisher_org_id, amount_minor, "
        "publisher_share_minor FROM fee_lines WHERE run_id = %s ORDER BY id",
        (run_id,),
    ).fetchall()


def test_a_listed_agent_call_writes_its_fee_through_the_runtime(runtime_env):  # noqa: F811
    conn = runtime_env
    agent, version = _listed_agent(conn)
    run_id, snapshot = _new_run(conn, edit=_uses(conn, agent))
    assert snapshot["fees"]["pack"] is None and snapshot["fees"]["agents"][agent]["unit_minor"] == AGENT_FEE

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        await _waiting(handle, "review")  # the matching step ran; the report step has not
        history = await handle.fetch_history()
        return json.dumps({"workflow_id": run_id, "history": json.loads(history.to_json())})

    recorded = asyncio.run(_drive(None, scenario))
    started = [e for e in _entries(conn, run_id) if e["type"] == "node.started" and e["node_id"] == "match"]
    lines = _fee_lines(conn, run_id)
    assert len(started) == 1 and len(lines) == len(started)  # one line per agent step attempt
    [line] = lines
    assert line["kind"] == "agent_call" and line["listing_version_id"] == version
    assert (line["buyer_org_id"], line["publisher_org_id"]) == ("org_demo", PUBLISHER)
    assert (line["amount_minor"], line["publisher_share_minor"]) == (AGENT_FEE, AGENT_FEE * 80 // 100)

    # Replaying the same history re-runs the workflow code, never its activities: no line is added.
    data = json.loads(recorded)
    history = WorkflowHistory.from_json(data["workflow_id"], data["history"])
    asyncio.run(Replayer(workflows=[PackRunner], plugins=adk_plugins()).replay_workflow(history))
    assert _fee_lines(conn, run_id) == lines
