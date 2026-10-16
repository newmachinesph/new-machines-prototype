"""Sub-project D, part 7: the publisher's numbers (installs, runs, earnings), simulated payouts by month, and
the ops overview's publishing numbers. A publisher sees only its own; buyers' runs are counted, not shown."""

from datetime import UTC, datetime

import pytest

from app import ops_live, publisher_stats
from app.defs import owners, registry
from tests.live_seed import add_org, add_run
from tests.publishing_seed import add_fee_line, add_listing, add_version, approve_and_list, defs_of
from tests.team_seed import _own, clone_agent, clone_pack
from tests.test_live_catalog import ana, ben, live, starts  # noqa: F401

PACK = "order-payment-reconciliation"
ACME, BUYER, OTHER = "org_acme000000000001", "org_buyer00000000002", "org_other00000000003"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def market(defs):
    for org, name in ((ACME, "Acme"), (BUYER, "Buyer Co"), (OTHER, "Other")):
        add_org(defs, org, name)
    defs.commit()
    agent = clone_agent(defs, "finance-agent", ACME, "matcher")
    pack = clone_pack(defs, PACK, ACME, "recon")
    ids = {}
    for kind, key in (("agent", agent), ("pack", pack)):
        listing = add_listing(defs, kind, key, ACME)
        version = add_version(defs, listing, 1, defs_of(defs, [(kind, key)]), price_minor=100)
        approve_and_list(defs, listing, version)
        ids[kind] = (listing, version, key)
    # BUYER added the pack; OTHER built its own pack with ACME's agent; ACME's own install is not counted.
    for org in (BUYER, ACME):
        defs.execute(
            "INSERT INTO installations (org_id, pack_slug, pack_version, cap_minor, reviewer_pool, "
            "installed_by) "
            "VALUES (%s, %s, 1, 2000, 'team', 'u')",
            (org, pack),
        )
    body = {**registry.latest(defs, "pack", PACK).body, "agents": [agent]}
    _own(defs, OTHER, "pack", owners.org_key(OTHER, "uses-matcher"), body)
    for run_id, at in (
        ("run_9301", NOW),
        ("run_9302", datetime(2026, 9, 3, tzinfo=UTC)),
        ("run_9303", datetime(2026, 8, 20, tzinfo=UTC)),
    ):
        add_run(defs, run_id, BUYER, at)
        add_fee_line(defs, run_id, ids["pack"][0], ids["pack"][1], BUYER, ACME, unit_minor=250, at=at)
    add_fee_line(
        defs,
        "run_9301",
        ids["agent"][0],
        ids["agent"][1],
        BUYER,
        ACME,
        event_key="a1",
        kind="agent_call",
        unit_minor=30,
        at=NOW,
    )
    defs.commit()
    return ids


def test_listing_numbers_count_other_workspaces_only(defs, market):
    numbers = publisher_stats.listing_numbers(defs, ACME, NOW)
    pack, agent = numbers[market["pack"][0]], numbers[market["agent"][0]]
    assert (pack.installs, pack.runs30d, pack.earnings_month_minor) == (1, 1, 200)
    assert (agent.installs, agent.runs30d, agent.earnings_month_minor) == (1, 1, 24)
    assert publisher_stats.listing_numbers(defs, BUYER, NOW) == {}


def test_earnings_this_month_and_simulated_payouts_by_month(defs, market):
    earned = publisher_stats.earnings(defs, ACME, NOW)
    assert earned.month.amount_minor == 224 and earned.simulated is True
    assert [(p.month, p.amount.amount_minor, p.status) for p in earned.payouts] == [
        ("2026-09", 200, "SIMULATED"),
        ("2026-08", 200, "SIMULATED"),
    ]
    assert publisher_stats.earnings(defs, BUYER, NOW).month.amount_minor == 0


def test_the_ops_overview_counts_reviews_and_publisher_earnings(defs, market):
    agent = clone_agent(defs, "finance-agent", ACME, "waiting")
    listing = add_listing(defs, "agent", agent, ACME)
    add_version(defs, listing, 1, defs_of(defs, [("agent", agent)]))
    defs.commit()
    assert publisher_stats.ops_numbers(defs, NOW) == (1, 224)
    overview = ops_live.overview(defs, NOW)
    assert overview.listings_in_review == 1 and overview.publisher_earnings_month.amount_minor == 224
    assert "publisherEarningsMonth" in overview.simulated_fields


def test_the_earnings_route_is_scoped_to_the_workspace(ana, ben):  # noqa: F811
    res = ana.get(f"/v1/organizations/{ana.org_id}/studio/earnings")
    assert (
        res.status_code == 200 and res.json()["month"]["amountMinor"] == 0 and res.json()["simulated"] is True
    )
    denied = ben.get(f"/v1/organizations/{ana.org_id}/studio/earnings")
    assert denied.status_code == 403 and denied.json()["code"] == "TENANT_SCOPE_DENIED"


def test_earnings_over_http_show_only_the_publishers_own_share(defs, ana, ben):  # noqa: F811
    add_org(defs, BUYER, "Buyer Co")
    agent = clone_agent(defs, "finance-agent", ana.org_id, "matcher")
    listing = add_listing(defs, "agent", agent, ana.org_id)
    version = add_version(defs, listing, 1, defs_of(defs, [("agent", agent)]), price_minor=100)
    approve_and_list(defs, listing, version)
    now = datetime.now(UTC)
    add_run(defs, "run_9401", BUYER, now)
    add_fee_line(
        defs, "run_9401", listing, version, BUYER, ana.org_id, kind="agent_call", unit_minor=250, at=now
    )
    defs.commit()
    mine = ana.get(f"/v1/organizations/{ana.org_id}/studio/earnings")
    assert mine.status_code == 200 and mine.json()["month"]["amountMinor"] == 200
    theirs = ben.get(f"/v1/organizations/{ben.org_id}/studio/earnings")
    assert theirs.status_code == 200 and theirs.json()["month"]["amountMinor"] == 0
    assert theirs.json()["payouts"] == []


def test_month_boundary_and_the_twelve_month_window(defs, market):
    listing, version, _ = market["pack"]
    edges = (
        ("run_9501", datetime(2025, 9, 30, 23, 59, 59, tzinfo=UTC)),  # before the window
        ("run_9502", datetime(2025, 10, 1, tzinfo=UTC)),  # the oldest payout month
        ("run_9503", datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)),  # last second of September
        ("run_9504", datetime(2026, 10, 1, tzinfo=UTC)),  # first instant of this month
    )
    for run_id, at in edges:
        add_run(defs, run_id, BUYER, at)
        add_fee_line(defs, run_id, listing, version, BUYER, ACME, unit_minor=100, at=at)
    defs.commit()
    earned = publisher_stats.earnings(defs, ACME, NOW)
    by_month = {p.month: p.amount.amount_minor for p in earned.payouts}
    # The market fixture already holds 200 in 2026-09 and 2026-08, and 224 this month.
    assert earned.month.amount_minor == 224 + 80
    assert by_month["2026-09"] == 200 + 80
    assert by_month["2025-10"] == 80 and "2025-09" not in by_month
    assert len(earned.payouts) <= publisher_stats.PAYOUT_MONTHS


def test_the_ops_overview_counts_checking_versions_whose_run_completed(defs, market):
    start = publisher_stats.ops_numbers(defs, NOW)[0]
    for n, status in enumerate(("COMPLETED", "FAILED", "RUNNING")):
        agent = clone_agent(defs, "finance-agent", ACME, f"checked{n}")
        run = f"run_96{n:02d}"
        add_run(defs, run, ACME, NOW, status=status)
        listing = add_listing(defs, "agent", agent, ACME)
        add_version(defs, listing, 1, defs_of(defs, [("agent", agent)]), status="checking", check_run_id=run)
    defs.commit()
    assert publisher_stats.ops_numbers(defs, NOW)[0] == start + 1  # only the completed run settles to review
