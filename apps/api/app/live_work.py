"""Live workspace runs, memory and reviewer earnings: real rows only, each query scoped to the actor's org,
except that earnings also include the network reviews the actor did for other orgs.

A run starts only for a pack the org has hired whose apps are all connected, with an input that matches the
pack's input schema (naming the org's own sheet when it writes to its own Google Sheets account) and a budget
that, with any publisher fee paid up front, is within the hire's per-run cap, while the month's spend is below
the workspace's monthly cap."""

import logging

from app import db, fees, listing_pins, live_catalog, live_connections, real_runs, workspace
from app.auth import Actor
from app.defs import registry
from app.defs.current import latest_bodies
from app.errors import ApiProblem, ProblemIssue
from app.models.common import Money, money_text
from app.models.org import MemoryItem, MemorySpaceOption
from app.models.requests import StartRunRequest
from app.models.runs import Run
from app.models.work import Earning
from app.redaction import scrub
from app.runtime import memory, routes
from app.runtime.memory import READABLE_BY_ORG, SHARED_SOURCES
from app.store import iso
from app.worker.activities import pay_minor  # one reading of a task's pay: earnings and the run's cost

log = logging.getLogger(__name__)

MEMORY_LIMIT = 200
EARNINGS_LIMIT = 100
# The source of an item an owner or admin added by hand (`created_by` holds who); always org-scoped.
TEAM_SOURCE = "team"
# Memory item sources as the customer sees them (a run's items are labelled with the run).
SOURCES = {"seed": "Definitions seed", "console": "New Machines", TEAM_SOURCE: "Your team"}
# Who adds to the org's memory (and retracts what the team added): the roles that invite and connect real
# accounts.
MANAGERS = workspace.INVITER_ROLES
# Active team items per org; past it, retract one before adding another.
MAX_TEAM_MEMORY = 100
_TEAM_MEMORY_LOCK = "team-memory:"  # one add at a time per org, so the count is exact
# A decided human task's outcome -> the reviewer's verdict, for tasks recorded without one.
VERDICTS = {"resolved": "APPROVED", "rejected": "REJECTED"}


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


# --- runs -----------------------------------------------------------------------------------------------

SHEETS_APP = "googlesheets"  # the connector key of Google Sheets
SHEET_FIELD = "spreadsheet_id"  # the run input naming the sheet a pack writes to
REAL_SHEET_NEEDED = (
    "Google Sheets is connected to your own account, so use the spreadsheet ID from your sheet's URL "
    "instead of the sandbox sheet."
)


def _check_real_sheet(org_id: str, slug: str, pack: dict, schema: dict | None, inp: dict) -> None:
    """A run that writes to the org's own Google Sheets account must name the org's own sheet: the input
    schema's default is the sandbox sheet, which no real account has. 422 at the field otherwise."""
    if SHEETS_APP not in [str(c) for c in pack.get("connectors") or []]:
        return
    prop = ((schema or {}).get("properties") or {}).get(SHEET_FIELD)
    if not isinstance(prop, dict) or "default" not in prop or inp.get(SHEET_FIELD) != prop["default"]:
        return
    if routes.current_route(org_id, SHEETS_APP).mode != "composio":
        return
    issue = ProblemIssue(kind="input", key=slug, path=SHEET_FIELD, message=REAL_SHEET_NEEDED)
    raise real_runs.invalid_input(schema, [issue])


def check_spend(org_id: str, upfront_minor: int = 0) -> None:
    """409 SPEND_CAP once this month's spend has reached the workspace's monthly cap, or when a listed pack's
    per-run fee (`upfront_minor`, paid at the start) would take it over."""
    org = workspace.organization(org_id)
    cap, spent = org.monthly_cap.amount_minor, org.month_spent.amount_minor
    if spent >= cap:
        raise ApiProblem(
            409,
            "SPEND_CAP",
            f"This month's spend has reached the workspace's monthly cap of {money_text(cap)}. "
            "New runs start again next month.",
        )
    if upfront_minor and spent + upfront_minor > cap:
        raise ApiProblem(
            409,
            "SPEND_CAP",
            f"This run's publisher fee of {money_text(upfront_minor)} would take this month's spend over the "
            f"workspace's monthly cap of {money_text(cap)}.",
        )


PACK_UNAVAILABLE = (
    "This Workflow Pack is no longer available from its publisher (for example, its listing was withdrawn), "
    "so new runs cannot start. Earlier runs and their results stay."
)


def _listed_terms(org_id: str, slug: str, pack_key: str, pack_version: int, defs, pack: dict):
    """(held, pack body, input schema, pack fee) of a run: the approved listing version and pins the org's
    installation of another workspace's listed pack holds (None for the platform's or its own), the body of
    the pack version the run will pin (whose apps and sheet the start checks), the input schema of what the
    run will pin, and the fee at that listing version. 409 PACK_UNAVAILABLE when the installation holds a
    version no longer available."""
    try:
        with db.connect() as conn:
            held = listing_pins.installed_bundle(conn, org_id, slug)
            if held is None:
                schema = live_catalog.input_schema(defs, pack)
                upfront = fees.pack_fee_minor(conn, org_id, pack_key, pack_version)
            else:
                schema = listing_pins.pinned_input_schema(conn, org_id, slug, held.pins)
                version = held.pins[("pack", pack_key)]
                pinned = registry.get_version(conn, "pack", pack_key, version)
                if pinned is None:
                    raise listing_pins.Unavailable(f"pack/{pack_key}@{version} is not in the registry")
                pack = pinned.body
                upfront = fees.pack_fee_minor(conn, org_id, pack_key, version, held.listing_version_id)
    except listing_pins.Unavailable as exc:  # any other error is a bug, never "unavailable"
        log.error("Cannot pin %s for %s: %s", slug, org_id, exc)
        raise ApiProblem(409, "PACK_UNAVAILABLE", PACK_UNAVAILABLE) from None
    return held, pack, schema, upfront


def _check_run_cap(run_cap: int, budget_minor: int, upfront_minor: int, name: str) -> None:
    """409 RUN_BUDGET_OVER_CAP when the budget, with the pack's per-run fee paid up front, is over the per-run
    spending cap set when the pack was added."""
    if budget_minor + upfront_minor <= run_cap:
        return
    cap = money_text(run_cap)
    if upfront_minor:
        detail = (
            f"The budget and the publisher fee of {money_text(upfront_minor)} come to more than the spending "
            f"cap of {cap} per run set when {name} was added. Lower the budget or raise the cap."
        )
    else:
        detail = (
            f"The budget is over the spending cap of {cap} per run set when {name} was added. Lower the "
            "budget or raise the cap."
        )
    raise ApiProblem(409, "RUN_BUDGET_OVER_CAP", detail)


def start_run(body: StartRunRequest, actor: Actor) -> Run:
    """Start a real run for the actor's org after the hire, connection, input and spend checks. Only a pack
    the org may see can start (the platform's, its own, or another workspace's listed one). The run pins the
    persisted ops connector settings (`ops_state.snapshot_policy`); a run of a listed pack pins the versions
    its installation holds, checks that version's apps and sheet, and pays its per-run fee up front, within
    the per-run cap (with the budget) and the monthly cap."""
    defs = live_catalog.definitions(actor.org_id)
    version = defs.pack(body.pack_slug)
    if version is None:
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {body.pack_slug}.")
    slug = live_catalog.slug_of(version)
    name = str(version.body.get("name") or slug)
    hire = live_catalog.installation(actor.org_id, slug)
    if hire is None:
        raise ApiProblem(409, "PACK_NOT_HIRED", f"Add {name} before starting a run.")
    held, pack, schema, upfront = _listed_terms(
        actor.org_id, slug, version.key, int(hire["pack_version"]), defs, version.body
    )
    missing = live_connections.missing_apps(actor.org_id, [str(c) for c in pack.get("connectors") or []])
    if missing:
        raise ApiProblem(
            409, "APPS_NOT_CONNECTED", f"Connect {_and(missing)} before starting a run of {name}."
        )
    inp = real_runs.check_input(slug, body.input, schema)
    _check_real_sheet(actor.org_id, slug, pack, schema, inp)
    _check_run_cap(int(hire["cap_minor"]), body.budget_minor, upfront, name)
    check_spend(actor.org_id, upfront)
    return real_runs.start_real_run(body.model_copy(update={"pack_slug": slug}), actor, None, inp, held=held)


# --- memory ---------------------------------------------------------------------------------------------


def readable_spaces(org_id: str) -> dict[str, dict]:
    """Memory space definitions this org may read: `readers` lists "*" or the org id."""
    return {
        key: body
        for key, body in latest_bodies("memory_space").items()
        if {"*", org_id} & set(body.get("readers") or [])
    }


def readable_space(org_id: str, space: str) -> dict:
    """The definition body of `space`; 422 unless the org may read it."""
    body = readable_spaces(org_id).get(space)
    if body is None:
        raise ApiProblem(422, "SCHEMA_INVALID", f"space: no memory space called {space}.")
    return body


def space_name(space: str, body: dict) -> str:
    return str(body.get("name") or space)


def memory_spaces(org_id: str) -> list[MemorySpaceOption]:
    """The spaces the org may add its own memory to: every space it may read, by name."""
    return [
        MemorySpaceOption(id=key, name=space_name(key, body)) for key, body in readable_spaces(org_id).items()
    ]


def require_manager(actor: Actor, action: str = "add a memory") -> None:
    """403 POLICY_DENIED unless the actor is an owner or admin of the org."""
    if actor.role not in MANAGERS:
        raise ApiProblem(403, "POLICY_DENIED", f"Only owners and admins can {action}.")


def _check_team_memory_cap(conn, org_id: str) -> None:
    """409 CONFLICT once the org has `MAX_TEAM_MEMORY` active team items. Takes the org's add lock for the
    transaction, so two adds at once cannot both pass the count."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_TEAM_MEMORY_LOCK + org_id,))
    [row] = conn.execute(
        "SELECT count(*) AS n FROM memory_items WHERE org_id = %s AND source = %s AND status = 'active'",
        (org_id, TEAM_SOURCE),
    ).fetchall()
    if row["n"] >= MAX_TEAM_MEMORY:
        raise ApiProblem(
            409,
            "CONFLICT",
            f"Your workspace has {MAX_TEAM_MEMORY} memories added by your team. Retract one before adding "
            "another.",
        )


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


def add_memory(actor: Actor, space: str, text: str) -> MemoryItem:
    """Add an item of the org's own to `space` (422 unless the org may read it). Runs of the org recall it
    from now on; no other org's do. The caller has checked the actor's role."""
    body = readable_space(actor.org_id, space)
    with db.connect() as conn:
        _check_team_memory_cap(conn, actor.org_id)
        item = memory.remember(conn, space, text, TEAM_SOURCE, actor.user_id, org_id=actor.org_id)
        row = _readable_item(conn, actor.org_id, item["id"])
        if row is None:  # the row was just written in this transaction
            raise RuntimeError(f"memory item {item['id']} was not readable by its own org")
        conn.commit()
    return _memory_item(row, {space: body})


def retract_memory(actor: Actor, item_id: str) -> MemoryItem:
    """Retract one of the org's own items: runs no longer recall it. Shared items belong to every org and
    cannot be retracted from one; what the team added, only an owner or admin retracts. No receipt entry is
    written."""
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
        if row["source"] == TEAM_SOURCE:
            require_manager(actor, "retract a memory added by your team")
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
