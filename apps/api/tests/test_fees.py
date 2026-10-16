"""Sub-project D, part 4: publisher fees. 80% to the publisher rounded down, the rest to the platform; one
line per charge at the pinned version's price; fees count toward the buyer's spend and show on Usage, per
listing."""

import asyncio
import threading
import time
from datetime import UTC, datetime

import pytest
from temporalio.exceptions import ApplicationError

from app import db as app_db
from app import fees, settings, workspace
from app.worker import activities
from tests.live_seed import add_org, add_run
from tests.publishing_seed import (
    add_fee_line,
    add_listing,
    add_publisher,
    add_version,
    approve_and_list,
    defs_of,
)
from tests.team_seed import clone_agent, clone_pack
from tests.test_workflow import (  # noqa: F401  (runtime_env is a fixture)
    _assert_sealed,
    _drive,
    _entries,
    _new_run,
    _run_row,
    _start,
    runtime_env,
)

PACK = "order-payment-reconciliation"
ACME, BUYER, OTHER = "org_acme000000000001", "org_buyer00000000002", "org_other00000000003"


@pytest.mark.parametrize(
    ("amount", "publisher", "platform"),
    [(0, 0, 0), (1, 0, 1), (5, 4, 1), (99, 79, 20), (100, 80, 20), (250, 200, 50), (333, 266, 67)],
)
def test_the_publisher_gets_80_percent_rounded_down(amount, publisher, platform):
    assert fees.split(amount) == (publisher, platform)


def test_a_negative_amount_is_refused():
    with pytest.raises(ValueError):
        fees.split(-1)


@pytest.fixture
def market(defs):
    """ACME lists an agent at 30 per call, a pack at 250 per run and a free agent; returns their ids."""
    for org, name in ((ACME, "Acme"), (BUYER, "Buyer Co"), (OTHER, "Other")):
        add_org(defs, org, name)
    defs.commit()
    add_publisher(defs, ACME, "Acme Labs")
    agent = clone_agent(defs, "finance-agent", ACME, "matcher", title="Matcher")
    free = clone_agent(defs, "finance-agent", ACME, "helper", title="Helper")
    pack = clone_pack(defs, PACK, ACME, "recon", title="Acme recon")
    out = {"agent": agent, "free": free, "pack": pack}
    for kind, key, name, price in (
        ("agent", agent, "Matcher", 30),
        ("agent", free, "Helper", 0),
        ("pack", pack, "Acme recon", 250),
    ):
        listing = add_listing(defs, kind, key, ACME, name=name)
        version = add_version(defs, listing, 1, defs_of(defs, [(kind, key)]), price_minor=price)
        approve_and_list(defs, listing, version)
        out[f"{key}:listing"], out[f"{key}:version"] = listing, version
    defs.commit()
    return out


def _snapshot(m: dict, org: str, pack_version: int = 1) -> dict:
    return {
        "org_id": org,
        "versions": [
            {"kind": "pack", "key": m["pack"], "version": pack_version},
            {"kind": "agent", "key": m["agent"], "version": 1},
            {"kind": "agent", "key": "finance-agent", "version": 1},
        ],
    }


def test_the_plan_charges_only_other_workspaces_approved_listings(defs, market):
    plan = fees.plan_fees(defs, _snapshot(market, BUYER), BUYER)
    assert plan["pack"] == {
        "listing_id": market[f"{market['pack']}:listing"],
        "version_id": market[f"{market['pack']}:version"],
        "publisher_org_id": ACME,
        "unit_minor": 250,
    }
    assert set(plan["agents"]) == {market["agent"]}  # the platform's agent has no fee
    assert fees.plan_fees(defs, _snapshot(market, ACME), ACME) == {"pack": None, "agents": {}}  # its own
    assert fees.plan_fees(defs, _snapshot(market, BUYER, pack_version=2), BUYER)["pack"] is None  # a draft
    assert fees.pack_fee_minor(defs, BUYER, market["pack"], 1) == 250
    assert fees.pack_fee_minor(defs, ACME, market["pack"], 1) == 0
    assert fees.pack_fee_minor(defs, BUYER, PACK, 1) == 0


def test_fee_lines_are_written_once_per_charge(defs, market):
    add_run(defs, "run_9101", BUYER, datetime.now(UTC))
    snapshot = {"org_id": BUYER, "fees": fees.plan_fees(defs, _snapshot(market, BUYER), BUYER)}
    for _ in range(2):  # a retry writes nothing more
        fees.record_pack_fee(defs, "run_9101", snapshot)
        fees.agent_fee_writer(snapshot, "run_9101", market["agent"], "a:1:fee:0")(defs)
    assert fees.agent_fee_writer(snapshot, "run_9101", "finance-agent", "x") is None
    assert fees.agent_fee_writer({"org_id": BUYER}, "run_9101", market["agent"], "x") is None  # no plan
    fees.record_pack_fee(defs, "run_9101", {"org_id": BUYER})  # a run started before fees: nothing
    defs.commit()
    rows = defs.execute(
        "SELECT kind, amount_minor, publisher_share_minor, platform_share_minor FROM fee_lines ORDER BY id"
    ).fetchall()
    assert [tuple(r.values()) for r in rows] == [("pack_run", 250, 200, 50), ("agent_call", 30, 24, 6)]


def test_fees_count_toward_the_buyers_spend_only(defs, market):
    add_run(defs, "run_9102", BUYER, datetime.now(UTC), ai=100)
    m = market
    add_fee_line(
        defs, "run_9102", m[f"{m['pack']}:listing"], m[f"{m['pack']}:version"], BUYER, ACME, unit_minor=250
    )
    defs.commit()
    assert workspace.month_spent(defs, BUYER) == 350
    assert workspace.month_spent(defs, ACME) == 0


def test_usage_itemizes_publisher_fees_per_listing(defs, market):
    m = market
    add_run(defs, "run_9103", BUYER, datetime.now(UTC), ai=100)
    add_fee_line(
        defs, "run_9103", m[f"{m['pack']}:listing"], m[f"{m['pack']}:version"], BUYER, ACME, unit_minor=250
    )
    for n in (1, 2):
        add_fee_line(
            defs,
            "run_9103",
            m[f"{m['agent']}:listing"],
            m[f"{m['agent']}:version"],
            BUYER,
            ACME,
            event_key=f"a:{n}",
            kind="agent_call",
            unit_minor=30,
        )
    add_fee_line(
        defs,
        "run_9103",
        m[f"{m['free']}:listing"],
        m[f"{m['free']}:version"],
        BUYER,
        ACME,
        event_key="f:1",
        kind="agent_call",
        unit_minor=0,
    )
    defs.commit()
    _, [txn] = workspace.usage(BUYER)
    assert txn.amount.amount_minor == 100 + 250 + 60
    assert (txn.lines[-1].account, txn.lines[-1].debit) == ("Publisher fees", 310)
    assert [
        (f.name, f.publisher, f.kind, f.quantity, f.unit.amount_minor, f.amount.amount_minor)
        for f in txn.fees
    ] == [
        ("Acme recon", "Acme Labs", "pack_run", 1, 250, 250),
        ("Matcher", "Acme Labs", "agent_call", 2, 30, 60),
    ]
    assert fees.items(defs, ["run_9103"], OTHER) == {}
    assert fees.items(defs, ["run_9103"], ACME) == {}  # the publisher never reads the buyer's run
    assert len(fees.items(defs, ["run_9103"], None)["run_9103"]) == 2  # ops


def test_a_run_without_fees_keeps_its_ledger_lines(defs, market):
    add_run(defs, "run_9104", BUYER, datetime.now(UTC), ai=100)
    defs.commit()
    _, [txn] = workspace.usage(BUYER)
    assert [line.account for line in txn.lines] == ["AI usage", "Tool usage", "Human review"]
    assert txn.fees is None


def test_the_agent_step_writes_its_fee_line_once(runtime_env, monkeypatch):  # noqa: F811
    db = runtime_env
    add_org(db, ACME, "Acme")
    add_org(db, "org_demo", "Demo Co")
    listing = add_listing(db, "agent", "finance-agent", ACME, name="Finance")
    version = add_version(db, listing, 1, [], price_minor=40)
    db.commit()
    fee = {"listing_id": listing, "version_id": version, "publisher_org_id": ACME, "unit_minor": 40}
    run_id, snapshot = _new_run(
        db, edit=lambda s: {**s, "fees": {"pack": None, "agents": {"finance-agent": fee}}}
    )
    workflow = next(iter(snapshot["defs"]["workflow"].values()))["body"]
    node = next(
        n for n in workflow["nodes"] if n["type"] == "agent" and n["config"]["agent"] == "finance-agent"
    )
    monkeypatch.setattr(activities.cel, "resolve", lambda inputs, state: {})
    call = activities.NodeCall(run_id=run_id, snapshot=snapshot, node_id=node["id"], state={})
    for _ in range(2):
        activities.PackActivities().start_agent(call)
    rows = db.execute("SELECT event_key, kind, amount_minor, buyer_org_id FROM fee_lines").fetchall()
    assert [tuple(r.values()) for r in rows] == [
        (activities.event_key(node["id"], 1, "fee", 0), "agent_call", 40, "org_demo")
    ]


# --- agent fees count against the caps as the calls happen ----------------------------------------------


def _finance_fee(db, price: int, **org: int) -> dict:
    """org_demo (with `org` columns, such as its monthly cap) and Acme's fee of `price` a call for the
    platform's finance agent, which the seed pack's matching step calls."""
    add_org(db, ACME, "Acme")
    add_org(db, "org_demo", "Demo Co", **org)
    listing = add_listing(db, "agent", "finance-agent", ACME, name="Finance")
    version = add_version(db, listing, 1, [], price_minor=price)
    db.commit()
    return {"listing_id": listing, "version_id": version, "publisher_org_id": ACME, "unit_minor": price}


def _charged(fee: dict, budget: int | None = None):
    def edit(snapshot: dict) -> dict:
        extra = {} if budget is None else {"budget_minor": budget}
        return {**snapshot, **extra, "fees": {"pack": None, "agents": {"finance-agent": fee}}}

    return edit


def _match_call(snapshot: dict, run_id: str) -> activities.NodeCall:
    return activities.NodeCall(run_id=run_id, snapshot=snapshot, node_id="match", state={})


def _stopped_at_the_fee(db, run_id: str, snapshot: dict, code: str) -> None:
    """The run ends FAILED at the matching step, before it starts, with `code` as its reason: no fee line."""

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        return await handle.result()

    assert asyncio.run(_drive(None, scenario)) == "FAILED"
    entries = _entries(db, run_id)
    [failed] = [e for e in entries if e["type"] == "run.failed"]
    assert failed["data"]["reason"].startswith(f"{code}: "), failed["data"]["reason"]
    assert not [e for e in entries if e["type"] == "node.started" and e["node_id"] == "match"]
    assert not [e for e in entries if e["type"] == "model.usage"]  # the agent never ran
    match = {n["id"]: n for n in _run_row(db, run_id)["projection"]["nodes"]}["match"]
    assert match["status"] == "FAILED" and match["note"] == failed["data"]["reason"]
    assert db.execute("SELECT 1 FROM fee_lines").fetchall() == []
    _assert_sealed(db, run_id, snapshot, "FAILED")


def test_an_agent_fee_over_the_monthly_cap_stops_the_run(runtime_env):  # noqa: F811
    db = runtime_env
    fee = _finance_fee(db, 40, monthly_cap_minor=1000)
    add_run(db, "run_9105", "org_demo", datetime.now(UTC), ai=980)  # 980 + 40 is over the 1000 cap
    db.commit()
    run_id, snapshot = _new_run(db, edit=_charged(fee))
    _stopped_at_the_fee(db, run_id, snapshot, "SPEND_CAP")


def test_an_agent_fee_over_the_run_budget_stops_the_run(runtime_env):  # noqa: F811
    db = runtime_env
    fee = _finance_fee(db, 40)
    run_id, snapshot = _new_run(db, edit=_charged(fee, budget=30))
    _stopped_at_the_fee(db, run_id, snapshot, "BUDGET_EXCEEDED")


@pytest.mark.parametrize(("price", "allowed"), [(20, True), (21, False)])
def test_the_run_budget_counts_ai_spend_and_earlier_agent_fees(runtime_env, monkeypatch, price, allowed):  # noqa: F811
    db = runtime_env
    fee = _finance_fee(db, price)
    run_id, snapshot = _new_run(db, edit=_charged(fee, budget=100))
    usage = (activities.event_key("plan", 1, "model.usage", 1), "model.usage", "plan", {"cost_minor": 50})
    activities.record_events(db, run_id, [usage])
    earlier = (fee["listing_id"], fee["version_id"], "org_demo", ACME)
    add_fee_line(db, run_id, *earlier, event_key="earlier:1:fee:0", kind="agent_call", unit_minor=30)
    db.commit()
    monkeypatch.setattr(activities.cel, "resolve", lambda inputs, state: {})
    call = _match_call(snapshot, run_id)
    if allowed:  # 50 AI + 30 earlier fee + 20 is exactly the budget of 100
        assert activities.PackActivities().start_agent(call)["fee_minor"] == 20
        return
    with pytest.raises(ApplicationError) as err:
        activities.PackActivities().start_agent(call)
    assert err.value.type == "BUDGET_EXCEEDED" and err.value.non_retryable
    db.commit()
    assert len(db.execute("SELECT 1 FROM fee_lines").fetchall()) == 1  # only the earlier line


def test_two_runs_of_one_workspace_never_both_fit_under_the_cap(defs, market):
    """Two agent steps of one workspace charge at once with room for one fee: the second waits for the first
    to commit, then sees its line and is refused."""
    defs.execute("UPDATE orgs SET monthly_cap_minor = 1000 WHERE id = %s", (BUYER,))
    add_run(defs, "run_9201", BUYER, datetime.now(UTC), ai=970)  # room for one 30 fee, not two
    for run_id in ("run_9202", "run_9203"):
        add_run(defs, run_id, BUYER, datetime.now(UTC), status="RUNNING")
    defs.commit()
    snapshot = {"org_id": BUYER, "fees": fees.plan_fees(defs, _snapshot(market, BUYER), BUYER)}
    written, outcomes = threading.Event(), {}

    def charge(run_id: str, first: bool) -> None:
        with app_db.connect(settings.test_database_url()) as conn:
            try:
                if not first:
                    written.wait(5)  # the first has charged and not committed yet
                conn.execute("SELECT 1 FROM runs WHERE id = %s FOR UPDATE", (run_id,))  # as record_events
                fees.agent_fee_writer(snapshot, run_id, market["agent"], "match:1:fee:1", 1000)(conn)
                if first:
                    written.set()
                    time.sleep(0.5)  # the second reaches its check meanwhile
                conn.commit()
                outcomes[run_id] = "charged"
            except fees.OverCap as exc:
                conn.rollback()
                outcomes[run_id] = exc.code

    threads = [
        threading.Thread(target=charge, args=("run_9202", True), daemon=True),
        threading.Thread(target=charge, args=("run_9203", False), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert outcomes == {"run_9202": "charged", "run_9203": fees.SPEND_CAP}
    defs.commit()
    assert [r["run_id"] for r in defs.execute("SELECT run_id FROM fee_lines").fetchall()] == ["run_9202"]


def test_a_workspace_that_no_longer_exists_is_never_charged(db):
    with pytest.raises(fees.OverCap) as err:
        fees.check_month(db, "org_nobody", 10, "A fee")
    assert (err.value.code, err.value.message) == (fees.SPEND_CAP, "This workspace no longer exists.")
    db.rollback()


def test_a_retried_agent_step_is_not_refused_by_its_own_fee(runtime_env, monkeypatch):  # noqa: F811
    db = runtime_env
    fee = _finance_fee(db, 40, monthly_cap_minor=1000)
    add_run(db, "run_9106", "org_demo", datetime.now(UTC), ai=960)  # 960 + 40 is exactly the cap
    db.commit()
    run_id, snapshot = _new_run(db, edit=_charged(fee, budget=40))
    monkeypatch.setattr(activities.cel, "resolve", lambda inputs, state: {})
    for _ in range(2):  # the retry finds its line already written: the month is at the cap now, not over
        activities.PackActivities().start_agent(_match_call(snapshot, run_id))
    db.commit()
    assert [r["amount_minor"] for r in db.execute("SELECT amount_minor FROM fee_lines").fetchall()] == [40]
