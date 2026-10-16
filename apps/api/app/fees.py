"""Publisher fees (sub-project D). Simulated: no money moves.

A run that uses another workspace's listed pack or agent pays its fee: the pack's per-run fee once at the
start, an agent's per-call fee each time an agent step runs. The run pins the fee plan in its snapshot
(`plan_fees`, at the price of the approved version it pinned), so a later price change never touches it, and
each charge is one `fee_lines` row written once. A line is written even at price 0 (the publisher's numbers
count every run); the buyer is shown only lines with an amount. A workspace's own listings carry no fees, so
a publisher's own sandbox tests and listing checks are free; a sandbox test of a pack that calls another
workspace's listed agent pays its per-call fee (never a pack fee: a test runs the org's own pack).

Fees count toward the caps as the calls happen: the pack fee within the per-run cap and the monthly cap at the
start (`live_work.start_run`), each agent call's fee within the run's budget and the monthly cap when the step
starts (`agent_fee_writer`); a call that would go over is refused before its line is written.
"""

from collections.abc import Callable
from typing import Any

from app.models.common import Money, money_text
from app.models.publishing import FeeItem

PUBLISHER_PERCENT = 80
SPEND_CAP = "SPEND_CAP"  # an agent call's fee would take the month over the workspace's monthly cap
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"  # ... or the run over its budget


class OverCap(Exception):
    """An agent call's fee would go over a cap: `code` (SPEND_CAP or BUDGET_EXCEEDED) and a message safe to
    show in the receipt."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# The approved version of a listed listing at definition version %(version)s, published by the definition's
# private owner (never a listing naming a platform key or another org's), newest decision first: the cap
# check (`pack_fee_minor`) and the charge (`plan_fees`) read the same row. A run of another workspace's
# listed pack passes the listing version its pins came from (%(held)s), so a version approved again at the
# same pack version charges its price only once the buyer updates.
_LISTED_VERSION = (
    "SELECT l.id AS listing_id, v.id AS version_id, l.publisher_org_id, v.price_minor "
    "FROM listings l JOIN listing_versions v ON v.listing_id = l.id "
    "JOIN definition_owners o ON o.kind = l.kind AND o.key = l.definition_key "
    "AND o.owner_kind = 'org' AND o.owner_id = l.publisher_org_id AND o.visibility = 'private' "
    "WHERE l.kind = %(kind)s AND l.definition_key = %(key)s AND v.definition_version = %(version)s "
    "AND v.status = 'approved' AND l.status = 'listed' AND l.publisher_org_id <> %(buyer)s "
    "AND (%(held)s::text IS NULL OR v.id = %(held)s) "
    "ORDER BY v.decided_at DESC, v.id DESC LIMIT 1"
)


def split(amount_minor: int) -> tuple[int, int]:
    """(publisher share, platform share): 80% to the publisher rounded down, the remainder to the platform."""
    if amount_minor < 0:
        raise ValueError("a fee is never negative")
    publisher = amount_minor * PUBLISHER_PERCENT // 100
    return publisher, amount_minor - publisher


def _listed(
    conn, kind: str, key: str, version: int, buyer_org_id: str, held: str | None = None
) -> dict | None:
    row = conn.execute(
        _LISTED_VERSION, {"kind": kind, "key": key, "version": version, "buyer": buyer_org_id, "held": held}
    ).fetchone()
    if row is None:
        return None
    return {
        "listing_id": row["listing_id"],
        "version_id": row["version_id"],
        "publisher_org_id": row["publisher_org_id"],
        "unit_minor": int(row["price_minor"]),
    }


def plan_fees(conn, snapshot: dict, buyer_org_id: str, pack_listing_version: str | None = None) -> dict:
    """The fees a run of `snapshot` owes, by what it pinned: {"pack": fee | None, "agents": {key: fee}}.
    `pack_listing_version` is the listing version the run's pins were taken from
    (`listing_pins.installed_bundle`): the pack is charged at that version's price, never at whatever the
    installation holds by the time the run is inserted."""
    plan: dict = {"pack": None, "agents": {}}
    for v in snapshot.get("versions") or []:
        if v["kind"] not in ("pack", "agent"):
            continue
        held = pack_listing_version if v["kind"] == "pack" else None
        fee = _listed(conn, v["kind"], v["key"], int(v["version"]), buyer_org_id, held)
        if fee is None:
            continue
        if v["kind"] == "pack":
            plan["pack"] = fee
        else:
            plan["agents"][v["key"]] = fee
    return plan


def pack_fee_minor(
    conn, buyer_org_id: str, pack_key: str, pack_version: int, listing_version: str | None = None
) -> int:
    """The per-run fee a run of this pack version owes up front (0 for the platform's or the org's own), at
    `listing_version` when the run pins one."""
    fee = _listed(conn, "pack", pack_key, pack_version, buyer_org_id, listing_version)
    return fee["unit_minor"] if fee else 0


def _insert(conn, run_id: str, event_key: str, kind: str, fee: dict, buyer_org_id: str) -> None:
    amount = fee["unit_minor"]  # one charge per line
    publisher, platform = split(amount)
    conn.execute(
        "INSERT INTO fee_lines (run_id, event_key, listing_id, listing_version_id, buyer_org_id, "
        "publisher_org_id, kind, quantity, unit_minor, amount_minor, publisher_share_minor, "
        "platform_share_minor) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s) "
        "ON CONFLICT (run_id, event_key) DO NOTHING",
        (
            run_id,
            event_key,
            fee["listing_id"],
            fee["version_id"],
            buyer_org_id,
            fee["publisher_org_id"],
            kind,
            fee["unit_minor"],
            amount,
            publisher,
            platform,
        ),
    )


def record_pack_fee(conn, run_id: str, snapshot: dict) -> None:
    """Write the pack's per-run fee line, when the run's fee plan has one. Does not commit."""
    fee = (snapshot.get("fees") or {}).get("pack")
    if fee:
        _insert(conn, run_id, "pack", "pack_run", fee, snapshot["org_id"])


def agent_fee(snapshot: dict, agent_key: str) -> dict | None:
    """The per-call fee the run's plan pins for `agent_key`, or None when the run owes it none."""
    return ((snapshot.get("fees") or {}).get("agents") or {}).get(agent_key) or None


WORKSPACE_GONE = "This workspace no longer exists."


def lock_monthly_cap(conn, org_id: str) -> int:
    """The workspace's monthly cap, its row locked FOR NO KEY UPDATE until the transaction ends (key-share
    foreign-key checks still pass). Every fee charge takes this lock before it reads the month's spend, so two
    charges of one workspace are checked one after the other and never both fit under the cap on the same
    spend. Lock order: no run row (`record_events`) is ever locked after it; a run start takes it before the
    installation (`real_runs._insert_run`), the order install and update use.
    OverCap SPEND_CAP when the workspace row is gone: nothing may be charged."""
    org = conn.execute(
        "SELECT monthly_cap_minor FROM orgs WHERE id = %s FOR NO KEY UPDATE", (org_id,)
    ).fetchone()
    if org is None:
        raise OverCap(SPEND_CAP, WORKSPACE_GONE)
    return int(org["monthly_cap_minor"])


def check_month(conn, org_id: str, amount: int, charge: str) -> None:
    """OverCap SPEND_CAP when `amount` more would take the workspace's month over its monthly cap, read under
    `lock_monthly_cap`. `charge` names the fee and its amount in the message."""
    from app import workspace  # workspace imports this module

    cap = lock_monthly_cap(conn, org_id)
    if workspace.month_spent(conn, org_id) + amount > cap:
        raise OverCap(
            SPEND_CAP,
            f"{charge} would take this month's spend over the workspace's monthly cap of {money_text(cap)}.",
        )


def _check_caps(conn, buyer_org_id: str, run_id: str, amount: int, budget_minor: int) -> None:
    """OverCap when `amount` more would take the buyer's month over its monthly cap, or the run's AI spend and
    agent fees over its budget (`budget_minor`, 0: no budget). The pack fee is outside the budget: it is paid
    up front, within the per-run cap with the budget (`live_work.start_run`)."""
    from app import workspace  # workspace imports this module

    check_month(conn, buyer_org_id, amount, f"A publisher fee of {money_text(amount)} for this step")
    if not budget_minor:
        return
    row = conn.execute(
        f"SELECT {workspace.RUN_AI_SPENT_SQL} AS ai, COALESCE((SELECT SUM(f.amount_minor) FROM fee_lines f "
        "WHERE f.run_id = runs.id AND f.kind = 'agent_call'), 0) AS fees FROM runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    used = int(row["ai"]) + int(row["fees"]) if row else 0
    if used + amount > budget_minor:
        raise OverCap(
            BUDGET_EXCEEDED,
            f"A publisher fee of {money_text(amount)} for this step would take the run's spend of "
            f"{money_text(used)} over its budget of {money_text(budget_minor)}.",
        )


def agent_fee_writer(
    snapshot: dict, run_id: str, agent_key: str, event_key: str, budget_minor: int = 0
) -> Callable[[Any], None] | None:
    """A `write(conn)` that records one call of `agent_key`, or None when the run owes it no fee. Run it in
    the transaction that holds the run's row lock (`record_events`): it first checks the fee against the
    monthly cap and the run's budget (`budget_minor`) and raises OverCap, writing nothing, when it would go
    over. A retry whose line is already written is not checked again: its own fee is already counted."""
    fee = agent_fee(snapshot, agent_key)
    if fee is None:
        return None
    buyer = snapshot["org_id"]

    def write(conn) -> None:
        written = conn.execute(
            "SELECT 1 FROM fee_lines WHERE run_id = %s AND event_key = %s", (run_id, event_key)
        ).fetchone()
        if written is not None:
            return
        if fee["unit_minor"]:
            _check_caps(conn, buyer, run_id, int(fee["unit_minor"]), budget_minor)
        _insert(conn, run_id, event_key, "agent_call", fee, buyer)

    return write


def items(conn, run_ids: list[str], buyer_org_id: str | None) -> dict[str, list[FeeItem]]:
    """{run id: its fee items} for the buyer's runs (None: any buyer, for ops): one item per listing and kind
    with an amount above 0, pack fees first, then by name."""
    if not run_ids:
        return {}
    rows = conn.execute(
        "SELECT f.run_id, f.listing_id, l.name, COALESCE(p.name, o.name) AS publisher, f.kind, f.unit_minor, "
        "SUM(f.quantity) AS quantity, SUM(f.amount_minor) AS amount FROM fee_lines f "
        "JOIN listings l ON l.id = f.listing_id JOIN orgs o ON o.id = f.publisher_org_id "
        "LEFT JOIN publishers p ON p.org_id = f.publisher_org_id "
        "WHERE f.run_id = ANY(%(runs)s) AND (%(buyer)s::text IS NULL OR f.buyer_org_id = %(buyer)s) "
        "GROUP BY f.run_id, f.listing_id, l.name, p.name, o.name, f.kind, f.unit_minor "
        "HAVING SUM(f.amount_minor) > 0 ORDER BY f.run_id, f.kind DESC, l.name",  # pack_run before agent_call
        {"runs": list(run_ids), "buyer": buyer_org_id},
    ).fetchall()
    out: dict[str, list[FeeItem]] = {}
    for r in rows:
        out.setdefault(r["run_id"], []).append(
            FeeItem(
                listing_id=r["listing_id"],
                name=r["name"],
                publisher=r["publisher"],
                kind=r["kind"],
                quantity=int(r["quantity"]),
                unit=Money(amount_minor=int(r["unit_minor"])),
                amount=Money(amount_minor=int(r["amount"])),
            )
        )
    return out
