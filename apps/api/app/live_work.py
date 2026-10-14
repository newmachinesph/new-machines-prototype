"""Live workspace runs, memory and reviewer earnings: real rows only, each query scoped to the actor's org,
except that earnings also include the network reviews the actor did for other orgs.

A run starts only for a pack the org has hired whose apps are all connected, with an input that matches the
pack's input schema and a budget within the hire's per-run cap, while the month's spend is below the
workspace's monthly cap."""

from app import db, live_catalog, live_connections, real_runs, workspace
from app.auth import Actor
from app.defs.current import latest_bodies
from app.errors import ApiProblem
from app.models.common import Money, money_text
from app.models.org import MemoryItem
from app.models.requests import StartRunRequest
from app.models.runs import Run
from app.models.work import Earning
from app.redaction import scrub
from app.runtime.memory import READABLE_BY_ORG, SHARED_SOURCES
from app.store import iso

MEMORY_LIMIT = 200
EARNINGS_LIMIT = 100
# Memory item sources as the customer sees them (a run's items are labelled with the run).
SOURCES = {"seed": "Definitions seed", "console": "New Machines"}
# A decided human task's outcome -> the reviewer's verdict, for tasks recorded without one.
VERDICTS = {"resolved": "APPROVED", "rejected": "REJECTED"}


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


# --- runs -----------------------------------------------------------------------------------------------


def start_run(body: StartRunRequest, actor: Actor) -> Run:
    """Start a real run for the actor's org after the hire, connection, input and spend checks. The run
    pins the persisted ops connector settings (`ops_state.snapshot_policy`)."""
    defs = live_catalog.definitions()
    version = defs.pack(body.pack_slug)
    if version is None:
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {body.pack_slug}.")
    pack, slug = version.body, live_catalog.slug_of(version)
    name = str(pack.get("name") or slug)
    hire = live_catalog.installation(actor.org_id, slug)
    if hire is None:
        raise ApiProblem(409, "PACK_NOT_HIRED", f"Add {name} before starting a run.")
    missing = live_connections.missing_apps(actor.org_id, [str(c) for c in pack.get("connectors") or []])
    if missing:
        raise ApiProblem(
            409, "APPS_NOT_CONNECTED", f"Connect {_and(missing)} before starting a run of {name}."
        )
    inp = real_runs.check_input(slug, body.input, live_catalog.input_schema(defs, pack))
    run_cap = int(hire["cap_minor"])
    if body.budget_minor > run_cap:
        raise ApiProblem(
            409,
            "RUN_BUDGET_OVER_CAP",
            f"The budget is over the spending cap of {money_text(run_cap)} per run set when {name} was "
            "added. Lower the budget or raise the cap.",
        )
    org = workspace.organization(actor.org_id)
    cap = org.monthly_cap.amount_minor
    if org.month_spent.amount_minor >= cap:
        raise ApiProblem(
            409,
            "SPEND_CAP",
            f"This month's spend has reached the workspace's monthly cap of {money_text(cap)}. "
            "New runs start again next month.",
        )
    return real_runs.start_real_run(body.model_copy(update={"pack_slug": slug}), actor, None, inp)


# --- memory ---------------------------------------------------------------------------------------------


def readable_spaces(org_id: str) -> dict[str, dict]:
    """Memory space definitions this org may read: `readers` lists "*" or the org id."""
    return {
        key: body
        for key, body in latest_bodies("memory_space").items()
        if {"*", org_id} & set(body.get("readers") or [])
    }


def source_label(source: str) -> tuple[str, str | None]:
    """(label, run id) of an item's source; a run writes "run:<run id>:<node>:<attempt>"."""
    if source.startswith("run:"):
        run_id = source.split(":")[1]
        return f"Run {run_id}", run_id
    return SOURCES.get(source, source), None


def _memory_item(row: dict, spaces: dict[str, dict]) -> MemoryItem:
    label, run_id = source_label(row["source"])
    return MemoryItem(
        id=row["id"],
        text=row["text"],
        scope="Organization",
        scope_name=str((spaces.get(row["space"]) or {}).get("name") or row["space"]),
        state="APPROVED",
        source=label,
        source_run=run_id,
        proposed_by=row["created_by"],
        created_at=iso(row["created_at"]),
        retracted=True if row["status"] == "retracted" else None,
    )


_MEMORY_SELECT = (
    "SELECT id, space, text, source, created_by, created_at, status, org_id FROM memory_items "
    f"WHERE {READABLE_BY_ORG} AND status IN ('active', 'retracted')"
)


def _params(org_id: str, **more) -> dict:
    return {"org": org_id, "shared": list(SHARED_SOURCES), **more}


def list_memory(org_id: str) -> list[MemoryItem]:
    """The org's own items and the shared ones (seed and console), in spaces the org may read, newest
    first. Retracted items stay listed, marked retracted; quarantined items never are."""
    spaces = readable_spaces(org_id)
    if not spaces:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            f"{_MEMORY_SELECT} AND space = ANY(%(spaces)s) ORDER BY created_at DESC, id DESC LIMIT %(limit)s",
            _params(org_id, spaces=list(spaces), limit=MEMORY_LIMIT),
        ).fetchall()
    return [_memory_item(r, spaces) for r in rows]


def _readable_item(conn, org_id: str, item_id: str, lock: bool = False) -> dict | None:
    return conn.execute(
        f"{_MEMORY_SELECT} AND id = %(id)s" + (" FOR UPDATE" if lock else ""),
        _params(org_id, id=item_id),
    ).fetchone()


def memory_exists(org_id: str, item_id: str) -> bool:
    with db.connect() as conn:
        return _readable_item(conn, org_id, item_id) is not None


def retract_memory(actor: Actor, item_id: str) -> MemoryItem:
    """Retract one of the org's own items: runs no longer recall it. Shared items belong to every org and
    cannot be retracted from one. No receipt entry is written."""
    with db.connect() as conn:
        row = _readable_item(conn, actor.org_id, item_id, lock=True)
        if row is None:
            raise ApiProblem(404, "NOT_FOUND", f"No memory {item_id}.")
        if row["org_id"] is None:
            raise ApiProblem(
                403,
                "POLICY_DENIED",
                "This is shared knowledge from New Machines; it can't be retracted here.",
            )
        if row["status"] != "retracted":
            conn.execute(
                "UPDATE memory_items SET status = 'retracted', retracted_by = %s, retracted_at = now() "
                "WHERE id = %s AND org_id = %s",
                (actor.user_id, item_id, actor.org_id),
            )
            row = {**row, "status": "retracted"}
        conn.commit()
    return _memory_item(row, readable_spaces(actor.org_id))


# --- earnings -------------------------------------------------------------------------------------------


def pay_minor(payload: dict) -> int:
    """The task's pay: `pay` in minor units, or a Money object; 0 without one."""
    pay = payload.get("pay")
    if isinstance(pay, dict):
        pay = pay.get("amountMinor", pay.get("amount_minor"))
    try:
        return max(int(pay or 0), 0)
    except TypeError, ValueError:
        return 0


def earnings(actor: Actor) -> list[Earning]:
    """The human tasks the actor decided, newest first: their org's (team reviews, unpaid: amount 0) and other
    orgs' taken through the reviewer network (simulated pay; the task's public id, and the org's name and
    contact details scrubbed from the title). `via` says which. No money moves, so each earning is
    simulated."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.id, t.public_id, t.status, t.payload, t.result, t.decided_at, o.name AS org_name, "
            "r.org_id = %(org)s AS own FROM run_tasks t JOIN runs r ON r.id = t.run_id "
            "JOIN orgs o ON o.id = r.org_id WHERE t.kind = 'human' AND t.decided_by = %(user)s "
            "AND t.decided_at IS NOT NULL "
            "AND (r.org_id = %(org)s OR t.payload->>'claimed_via' = 'network') "
            "ORDER BY t.decided_at DESC, t.id DESC LIMIT %(limit)s",
            {"org": actor.org_id, "user": actor.user_id, "limit": EARNINGS_LIMIT},
        ).fetchall()
    out = []
    for row in rows:
        payload, result = row["payload"] or {}, row["result"] or {}
        verdict = result.get("verdict") or VERDICTS.get(row["status"], "REJECTED")
        title = str(payload.get("title") or "Review the result")
        own = row["own"]
        # A claim taken through the network keeps its simulated pay even if its holder later joined the org.
        network = not own or payload.get("claimed_via") == "network"
        out.append(
            Earning(
                task_id=row["id"] if own else row["public_id"],
                title=title if own else scrub(title, row["org_name"]),
                at=iso(row["decided_at"]),
                amount=Money(amount_minor=pay_minor(payload) if network else 0),
                verdict=verdict,
                status="PAID_SIMULATED",
                simulated=True,
                via="network" if network else "team",
            )
        )
    return out
