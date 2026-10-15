"""Seed rows for the live ops console tests (connectors, overview): orgs, connections, runs, tasks and
receipt entries written straight into Postgres with fixed timestamps, so every window is deterministic."""

from datetime import UTC, datetime

from psycopg.types.json import Jsonb

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
TODAY = datetime(2026, 10, 12, tzinfo=UTC)
PERMIT, DENY = "PERMIT", "DENY"


def add_org(db, org_id: str, name: str, **cols) -> None:
    columns = {"id": org_id, "name": name, **cols}
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    db.execute(f"INSERT INTO orgs ({names}) VALUES ({marks})", tuple(columns.values()))


def connect(db, org_id: str, app: str, status: str) -> None:
    """A connection row in the state `status`: sandbox data when sandbox, else the org's own Composio account,
    which a `connected` row has (so a run could reach it, `routes.route_of`)."""
    mode = "sandbox" if status == "sandbox" else "composio"
    account = f"ca_{org_id}" if status == "connected" else None
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, connected_by, account_id) "
        "VALUES (%s, %s, %s, %s, 'u', %s)",
        (org_id, app, status, mode, account),
    )


def _money(minor: int) -> dict:
    return {"amountMinor": minor, "currency": "USD"}


def add_run(
    db,
    run_id: str,
    org_id: str,
    at: datetime,
    status: str = "COMPLETED",
    pack: str = "order-payment-reconciliation",
    ai: int = 0,
    tools: int = 0,
    human: int = 0,
) -> None:
    projection = {
        "id": run_id,
        "status": status,
        "spent": {"ai": _money(ai), "tools": _money(tools), "human": _money(human)},
    }
    db.execute(
        "INSERT INTO runs (id, org_id, pack_slug, status, snapshot, projection, input, created_at) "
        "VALUES (%s, %s, %s, %s, '{}', %s, '{}', %s)",
        (run_id, org_id, pack, status, Jsonb(projection), at),
    )


def add_task(db, task_id: str, run_id: str, kind: str, status: str) -> None:
    db.execute(
        "INSERT INTO run_tasks (id, run_id, node_id, kind, status, payload) "
        "VALUES (%s, %s, 'n', %s, %s, '{}')",
        (task_id, run_id, kind, status),
    )


def add_entry(
    db,
    run_id: str,
    seq: int,
    at: datetime,
    connector: str,
    ok: bool,
    verdict: str = PERMIT,
    kind: str = "tool.call",
    app: str | None = None,
) -> None:
    """A receipt entry shaped like `worker.activities._tool_event`: the `<connector>.<tool>` ref, the
    display app, whether the call succeeded and the policy verdict."""
    data = {
        "tool_ref": f"{connector}.some_tool",
        "app": app or connector.capitalize(),
        "ok": ok,
        "policy": {"verdict": verdict, "reason_codes": [], "ref": "policy"},
    }
    db.execute(
        "INSERT INTO receipt_entries (run_id, seq, event_key, at, type, data, prev_hash, hash) "
        "VALUES (%s, %s, %s, %s, %s, %s, '', '')",
        (run_id, seq, f"e{seq}", at, kind, Jsonb(data)),
    )
