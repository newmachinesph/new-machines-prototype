"""The ops overview in the live workspace: counts, spend and series read from every org's rows, with day
windows starting at 00:00 UTC; only the platform daily cap and the incident count stay fixtures."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ops_live, ops_state
from app.store import reset_store
from tests.live_seed import DENY, NOW, TODAY, add_entry, add_org, add_run, add_task

OPS = {"Authorization": "Bearer ops"}  # signs in as the ops admin of the `live_ops` fixture
OPR = "order-payment-reconciliation"
REFUND = "refund-triage"
OVERDUE = "overdue-invoice-follow-up"


def _at(hours: float) -> datetime:
    return TODAY + timedelta(hours=hours)


@pytest.fixture
def busy(defs):
    """Five orgs and their runs around NOW (2026-10-12 15:00 UTC).

    acme (trial, cap $100):  a1 01:30 COMPLETED (AI 300, tools 50, human 100), a2 09:10 FAILED (AI 200),
                             a3 09:40 RUNNING with an open human task, a4 14:20 WAITING_FOR_HUMAN with a
                             pending approval, y1 23:59 yesterday COMPLETED (AI 1000), p1 Sep 28 (last month,
                             AI 5000, refund-triage), x1 Sep 1 (outside 30 days, overdue follow-up).
    bolt (pro, cap $20):     b1 09:05 COMPLETED (AI 1500, human 300) with an approved approval: 90% of cap.
                             o1 Oct 3 FAILED (refund-triage): outside the 7-day success window.
    dune (pro, cap $10):     d1 Oct 2 COMPLETED (AI 850, overdue follow-up): 85% of its cap.
    cora (trial, suspended, cap $1): c1 Oct 5 00:00 COMPLETED (AI 100): 100% of its cap, but suspended.
    eve (pro, cap 0):        no runs and no cap, so no cap item.
    """
    reset_store()  # the platform daily cap is the fixture's
    db = defs
    add_org(db, "org_acme", "Acme Foods", plan="trial", monthly_cap_minor=10000)
    add_org(db, "org_bolt", "Bolt Labs", plan="pro", monthly_cap_minor=2000)
    add_org(db, "org_dune", "Dune", plan="pro", monthly_cap_minor=1000)
    add_org(db, "org_cora", "Cora", plan="trial", status="suspended", monthly_cap_minor=100)
    add_org(db, "org_eve", "Eve", plan="pro", monthly_cap_minor=0)
    add_run(db, "a1", "org_acme", _at(1.5), ai=300, tools=50, human=100)
    add_run(db, "a2", "org_acme", _at(9 + 10 / 60), "FAILED", ai=200)
    add_run(db, "a3", "org_acme", _at(9 + 40 / 60), "RUNNING")
    add_run(db, "a4", "org_acme", _at(14 + 20 / 60), "WAITING_FOR_HUMAN")
    add_run(db, "y1", "org_acme", TODAY - timedelta(minutes=1), ai=1000)
    add_run(db, "p1", "org_acme", datetime(2026, 9, 28, tzinfo=UTC), pack=REFUND, ai=5000)
    add_run(db, "x1", "org_acme", datetime(2026, 9, 1, tzinfo=UTC), pack=OVERDUE)
    add_run(db, "b1", "org_bolt", _at(9 + 5 / 60), ai=1500, human=300)
    add_run(db, "o1", "org_bolt", datetime(2026, 10, 3, tzinfo=UTC), "FAILED", pack=REFUND)
    add_run(db, "d1", "org_dune", datetime(2026, 10, 2, tzinfo=UTC), pack=OVERDUE, ai=850)
    add_run(db, "c1", "org_cora", datetime(2026, 10, 5, tzinfo=UTC), ai=100)
    add_task(db, "t1", "a3", "human", "open")
    add_task(db, "t2", "a1", "human", "done")
    add_task(db, "t3", "a4", "approval", "pending")
    add_task(db, "t4", "b1", "approval", "approved")
    db.commit()
    return db


def test_the_kpis_count_every_orgs_rows_by_utc_day(busy):
    kpis = ops_live.overview(busy, NOW).kpis.model_dump(by_alias=True)
    assert kpis == {
        "activeTenants": 4,  # acme, bolt, dune, eve; cora is suspended
        "trialTenants": 2,  # acme and cora are on the trial plan
        "runsToday": 5,  # a1-a4 and b1; y1 at 23:59 yesterday is not today
        "runSuccessRate7d": 0.75,  # a1, b1, y1 completed; a2 failed; o1 is older than 7 days
        "openHumanTasks": 1,
        "pendingApprovals": 1,
        "aiSpendToday": {"amountMinor": 300 + 200 + 1500, "currency": "USD"},
        "platformDailyCap": {"amountMinor": 60000, "currency": "USD"},
        "incidentsOpen": 0,
    }


def test_runs_by_hour_split_todays_runs_by_utc_hour(busy):
    hours = ops_live.overview(busy, NOW).runs_by_hour
    assert [h.hour for h in hours] == list(range(24))
    busy_hours = {
        h.hour: (h.completed, h.failed, h.waiting) for h in hours if h.completed + h.failed + h.waiting
    }
    # a1 at 01:30; b1, a2 and a3 (an open task) at 09:xx; a4 (WAITING_FOR_HUMAN) at 14:20. Nothing at 23:00.
    assert busy_hours == {1: (1, 0, 0), 9: (1, 1, 1), 14: (0, 0, 1)}


def test_a_run_at_midnight_is_todays_and_tomorrows_runs_are_not(busy):
    add_run(busy, "m1", "org_acme", TODAY, "FAILED", ai=7)  # 00:00:00 UTC exactly
    add_run(busy, "n1", "org_acme", TODAY + timedelta(days=1), ai=11)  # 00:00 tomorrow
    busy.commit()
    view = ops_live.overview(busy, NOW)
    assert (view.kpis.runs_today, view.kpis.ai_spend_today.amount_minor) == (6, 2000 + 7)
    assert (view.runs_by_hour[0].failed, sum(h.completed for h in view.runs_by_hour)) == (1, 2)


def test_an_ended_run_is_never_waiting(busy):
    add_run(busy, "z1", "org_acme", _at(14.75), "CANCELLED")
    add_task(busy, "t5", "z1", "human", "open")  # left open when the run was cancelled
    busy.commit()
    hours = ops_live.overview(busy, NOW).runs_by_hour
    assert (hours[14].completed, hours[14].failed, hours[14].waiting) == (0, 0, 1)  # a4 only


def test_spend_this_month_and_the_top_packs(busy):
    view = ops_live.overview(busy, NOW)
    # October: a1 450 + a2 200 + y1 1000 + b1 1800 + o1 0 + d1 850 + c1 100; p1 is September.
    assert view.spend_month.model_dump() == {"amount_minor": 4400, "currency": "USD"}
    assert [(p.slug, p.name, p.runs) for p in view.top_packs] == [
        (OPR, "Order & Payment Reconciliation", 7),
        (REFUND, "Refund Triage", 2),
        (OVERDUE, "Overdue Invoice Follow-up", 1),  # x1 is older than 30 days
    ]


def test_attention_lists_tenant_caps_and_failing_connectors(busy):
    for seq, ok in enumerate((True, False, True)):
        add_entry(busy, "a1", seq, _at(2), "shopify", ok)  # 1 of 3 failed today
    for seq in range(3, 6):
        add_entry(busy, "a1", seq, _at(2), "shopify", ok=False, verdict=DENY)  # never reached Shopify
    for seq in range(25):
        add_entry(busy, "b1", seq, _at(10), "stripe", ok=seq != 0)  # 1 of 25: under 5%
    for seq in range(5):
        add_entry(busy, "a2", seq, _at(11), "gmail", ok=False, verdict=DENY)  # denied only: no error
    add_entry(busy, "y1", 0, TODAY - timedelta(minutes=1), "gmail", ok=False)  # yesterday
    busy.commit()
    items = ops_live.overview(busy, NOW).attention
    assert [(i.kind, i.severity, i.title, i.href) for i in items] == [
        ("tenant_cap", "warn", "Bolt Labs is at 90% of its monthly cap", "/tenants/org_bolt"),
        ("connector_error", "warn", "Shopify connector is failing", "/connectors?c=shopify"),
        ("tenant_cap", "info", "Dune is at 85% of its monthly cap", "/tenants/org_dune"),
    ]
    assert items[0].detail == "$18.00 of $20.00 spent."
    assert items[1].detail == "Error rate 33.3% of 3 calls today, at or above the 5% limit."
    assert {i.at for i in items} == {"2026-10-12T15:00:00Z"}


def test_recent_audit_is_the_newest_eight_entries(busy):
    for n in range(10):
        ops_state.audit(
            busy, "ops@example.com", "tenant.suspend", "tenant", f"org_{n}", "r", {"summary": f"#{n}"}
        )
    busy.commit()
    recent = ops_live.overview(busy, NOW).recent_audit
    assert [e.summary for e in recent] == [f"#{n}" for n in range(9, 1, -1)]


def test_a_naive_now_is_refused(busy):
    with pytest.raises(ValueError):
        ops_live.overview(busy, NOW.replace(tzinfo=None))


def test_an_empty_platform_reads_zero(defs):
    view = ops_live.overview(defs, NOW)
    assert (view.kpis.active_tenants, view.kpis.runs_today, view.kpis.run_success_rate7d) == (0, 0, 1.0)
    assert (view.attention, view.recent_audit, view.top_packs) == ([], [], [])
    assert view.spend_month.amount_minor == 0


# --- through the API ------------------------------------------------------------------------------------


def test_the_live_overview_marks_only_the_fixture_fields_simulated(live_ops: TestClient, busy):
    res = live_ops.get("/v1/ops/overview", headers=OPS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["simulatedFields"] == [
        "kpis.platformDailyCap",
        "kpis.incidentsOpen",
        "publisherEarningsMonth",
    ]
    assert body["kpis"]["activeTenants"] == 4 and len(body["runsByHour"]) == 24
    assert body["topPacks"][0] == {"slug": OPR, "name": "Order & Payment Reconciliation", "runs": 7}
    assert set(body["spendMonth"]) == {"amountMinor", "currency"}


def test_the_demo_overview_is_unchanged(client):
    body = client.get("/v1/ops/overview").json()
    assert set(body) == {"kpis", "attention", "recentAudit", "runsByHour", "simulatedFields"}
    assert body["simulatedFields"] == [
        "kpis.runsToday",
        "kpis.runSuccessRate7d",
        "kpis.aiSpendToday",
        "runsByHour",
    ]
