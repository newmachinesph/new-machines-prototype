"""Submitting a Studio agent or pack for the marketplace (sub-project D): the automatic checks, then the
version in `listings`. A failed definition check or the private-agent rule refuses the submission with the
reasons and records nothing, as does anything that uses the org's own MCP server (409 NOT_PUBLISHABLE); the
sandbox check decides when the version reaches the ops queue (`listings.settle_checks`)."""

from dataclasses import dataclass
from typing import Literal

from psycopg.types.json import Jsonb

from app import db, listings, publishers, real_runs, settings, studio
from app import studio_build as build
from app.auth import Actor
from app.defs import owners, registry
from app.defs.model import Definition
from app.defs.snapshot import build_snapshot
from app.errors import ApiProblem
from app.live_work import check_spend
from app.models.publishing import SubmitListingRequest
from app.models.requests import StartRunRequest
from app.models.studio import PackDraft, SandboxRunRequest, StepDraft
from app.runtime.drivers import MCP_TRANSPORT

DEFINITION_PASSED = "The definition checks found no problems."
AGENTS_PASSED = "Every agent in the pack is the platform's or listed."
SANDBOX_REUSED = "A sandbox test of this version completed."
SANDBOX_RUNNING = "A sandbox run of this version is running."
CHECK_BUDGET_MINOR = 500
MIN_DRAFT_BUDGET_MINOR = 100  # `PackDraft.budget_minor`'s floor; the run keeps the budget it was given
CHECK_NAME = studio.CHECK_NAME
CHECK_STEP = "call"
NAME_MAX = 80
# The check pack takes any input: the publisher's sample goes to the agent as it is.
FREE_INPUT = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Sample", "type": "object"}

LISTED_ELSEWHERE = "listed by another workspace"  # `listings.submit`'s ValueError for another org's listing

NOT_PUBLISHABLE = "NOT_PUBLISHABLE"
NOT_PUBLISHABLE_DETAIL = (
    "Anything that uses your own MCP server stays in your workspace. "
    "It cannot be submitted to the marketplace."
)

Kind = Literal["agent", "pack"]


@dataclass(frozen=True)
class _Checked:
    """A saved definition that passed the checks made before any run: what to record and whether a completed
    sandbox test of this version already exists."""

    saved: registry.Version
    name: str
    checks: list[dict]
    bundle: list[dict]
    reused: dict | None  # the completed sandbox test reused: {id, input}


def _not_found(kind: str, key: str) -> ApiProblem:
    """As `studio._own` answers a definition that is not the org's own."""
    return ApiProblem(404, "NOT_FOUND", f"Your Studio has no {kind} called {key}.")


def check_pack_key(org_id: str) -> str:
    return owners.org_key(org_id, CHECK_NAME)


def _profile(conn, actor: Actor) -> None:
    publishers.require_manager(actor)
    if publishers.active(conn, actor.org_id) is None:
        raise ApiProblem(
            409, "PUBLISHER_PROFILE_REQUIRED", "Turn on publishing in Settings before you submit."
        )


def _no_open_version(conn, kind: str, key: str) -> None:
    existing = listings.find(conn, kind, key)
    if existing and listings.open_version(conn, existing["id"]) is not None:
        raise ApiProblem(409, "SUBMISSION_OPEN", "A version of this is already waiting for review.")


def _agent_state(conn, listing: dict | None) -> str:
    """Where an unlisted agent stands, in words: what it still needs before a pack can use it. A listing that
    never had a version was never submitted."""
    if listing is None or not listings.versions(conn, listing["id"]):
        return "not submitted"
    if listings.open_version(conn, listing["id"]) is not None:
        return "in review"
    return "unlisted" if listing["status"] == "unlisted" else "not approved"


def _private_agents(conn, org_id: str, snapshot: dict) -> list[str]:
    """The org's own agents in the pack that are not listed, each as "<name> (<state>)" (another org's agent
    is pinned only when listed, and the platform's are public)."""
    names = []
    for v in snapshot["versions"]:
        if v["kind"] != "agent" or not owners.in_org(v["key"], org_id):
            continue
        listing = listings.find(conn, "agent", v["key"])
        if listing is None or listing["status"] != "listed":
            body = snapshot["defs"]["agent"][v["key"]]["body"]
            names.append(f"{body.get('name') or v['key']} ({_agent_state(conn, listing)})")
    return sorted(names)


def _connector_keys(kind: str, body: dict) -> set[str]:
    """The connectors a saved pack names (its agents' tools included), or an agent's tools use."""
    if kind == "pack":
        return {str(c) for c in body.get("connectors") or []}
    return {str(ref).partition(".")[0] for ref in (body.get("runtime") or {}).get("tools") or []}


def _publishable(conn, org_id: str, kind: str, saved: registry.Version) -> None:
    """409 NOT_PUBLISHABLE when the definition uses one of the org's own MCP servers: their connectors are
    private to the org, so no buyer could run it."""
    for key in sorted(_connector_keys(kind, saved.body)):
        if not owners.in_org(key, org_id):
            continue
        connector = registry.latest(conn, "connector", key)
        if connector is not None and connector.body.get("transport") == MCP_TRANSPORT:
            raise ApiProblem(409, NOT_PUBLISHABLE, NOT_PUBLISHABLE_DETAIL)


def _own_bundle(snapshot: dict, org_id: str) -> list[dict]:
    """The org's own definitions the pack pinned, minus its agents (each is listed on its own). Never a
    platform definition: one in a bundle would override it for every buyer."""
    return [
        {"kind": v["kind"], "key": v["key"], "version": int(v["version"])}
        for v in snapshot["versions"]
        if v["kind"] != "agent" and owners.in_org(v["key"], org_id)
    ]


def _agent_bundle(conn, org_id: str, key: str, saved: registry.Version, run_id: str) -> list[dict]:
    """The agent and the org's own schemas it names, each at the version the check run pinned: a schema
    saved while the check started was not tested, so it is not recorded."""
    refs = {str(saved.body.get(f) or "") for f in ("input_schema_ref", "output_schema_ref")}
    out = [{"kind": "agent", "key": key, "version": saved.version}]
    row = conn.execute(
        "SELECT snapshot->'versions' AS versions FROM runs WHERE id = %s", (run_id,)
    ).fetchone()
    pinned = {
        v["key"]: int(v["version"]) for v in (row["versions"] if row else None) or [] if v["kind"] == "schema"
    }
    for ref in sorted(r for r in refs if r and owners.in_org(r, org_id) and r in pinned):
        out.append({"kind": "schema", "key": ref, "version": pinned[ref]})
    return out


def _pinned(kind: str, key: str, version: int) -> Jsonb:
    """A `runs.snapshot->'versions'` containment test: the run pinned kind/key at `version`."""
    return Jsonb([{"kind": kind, "key": key, "version": version}])


def _completed_test(conn, org_id: str, key: str, version: int) -> dict | None:
    """The newest completed sandbox test of exactly this pack version: {id, input}."""
    return conn.execute(
        "SELECT id, input FROM runs WHERE org_id = %s AND pack_slug = %s AND status = 'COMPLETED' "
        "AND (projection->>'sandboxTest')::boolean IS TRUE AND snapshot->'versions' @> %s "
        "ORDER BY created_at DESC LIMIT 1",
        (org_id, key, _pinned("pack", key, version)),
    ).fetchone()


def _definition_issues(conn, actor: Actor, kind: str, key: str, saved: registry.Version) -> None:
    """The Studio's own validation of the saved draft; 422 INVALID_DEFINITION with each issue."""
    ctx, org = studio._context(conn, actor.org_id), studio._org(actor)
    if kind == "agent":
        issues = studio._agent_issues(ctx, key, org, build.agent_draft(saved.body, saved.files))
    else:
        issues = studio._pack_issues(ctx, key, org, studio._pack(conn, actor.org_id, key).draft)
    if issues:
        raise studio._invalid(issues)


def _pack_checks(conn, org_id: str, key: str) -> tuple[list[dict], list[dict]]:
    """The private-agent rule (422 PRIVATE_AGENTS naming the agents) and the pack's bundle."""
    try:
        snapshot = build_snapshot(conn, key, org_id, {}, set())
    except LookupError:
        raise ApiProblem(
            409,
            "PACK_UNAVAILABLE",
            "This Workflow Pack uses an agent this workspace can no longer reach. Check its agents in the "
            "Studio, save the pack again, then submit it.",
        ) from None
    # A listed agent can carry an MCP tool the pack's own `connectors` no longer name (the tool was switched
    # off): the snapshot still pins its connector, and the bundle must never publish it.
    for ckey, connector in (snapshot["defs"].get("connector") or {}).items():
        if owners.in_org(ckey, org_id) and (connector["body"] or {}).get("transport") == MCP_TRANSPORT:
            raise ApiProblem(409, NOT_PUBLISHABLE, NOT_PUBLISHABLE_DETAIL)
    if private := _private_agents(conn, org_id, snapshot):
        raise ApiProblem(
            422, "PRIVATE_AGENTS", f"These agents need to be listed first: {', '.join(private)}."
        )
    return [{"name": "agents", "state": "passed", "detail": AGENTS_PASSED}], _own_bundle(snapshot, org_id)


def _check(actor: Actor, kind: Kind, key: str) -> _Checked:
    """Every check made before a sandbox run starts. A failed sandbox check that has ended is settled first,
    so it no longer holds the listing open."""
    with db.connect() as conn:
        _profile(conn, actor)
        listings.settle_checks(conn, actor.org_id)
        conn.commit()  # settle_checks locks listings: release them before anything else
        saved = studio._own(conn, actor.org_id, kind, key)
        _publishable(conn, actor.org_id, kind, saved)
        _definition_issues(conn, actor, kind, key, saved)
        checks = [{"name": "definition", "state": "passed", "detail": DEFINITION_PASSED}]
        if kind == "pack":
            more, bundle = _pack_checks(conn, actor.org_id, key)
            checks += more
            reused = _completed_test(conn, actor.org_id, key, saved.version)
        else:
            bundle, reused = [], None  # an agent's bundle is read from its check run (`submit`)
        _no_open_version(conn, kind, key)
    return _Checked(saved, str(saved.body.get("name") or key), checks, bundle, reused)


def _sandbox_ready(actor: Actor) -> None:
    if settings.connector_mode() != settings.SANDBOX_MODE:
        raise ApiProblem(
            409,
            "SANDBOX_UNAVAILABLE",
            "Checks need the platform's sandbox connectors, which this deployment does not use.",
        )
    check_spend(actor.org_id)


def _check_draft(agent_key: str, name: str, budget: int) -> PackDraft:
    """A one-step pack that calls the agent with the run's input as `sample`. Its maximum is at least
    `PackDraft`'s floor; the run's own budget may be lower."""
    return PackDraft(
        name=f"Listing check: {name}"[:NAME_MAX],
        outcome="Checks that the agent answers on sandbox data.",
        description="Built for a marketplace submission and never saved.",
        human_review="None.",
        budget_minor=max(budget, MIN_DRAFT_BUDGET_MINOR),
        entry_step="start",
        steps=[
            StepDraft(id="start", type="trigger", routes={"next": CHECK_STEP}),
            StepDraft(
                id=CHECK_STEP,
                type="agent",
                config={
                    "agent": agent_key,
                    "task": "Answer the sample request. Submit the result in the required shape.",
                    "inputs": {"sample": "=input"},
                },
                routes={"next": "done"},
            ),
            StepDraft(
                id="done", type="end", config={"status": "COMPLETED", "deliverable": "=nodes.call.output"}
            ),
        ],
    )


def _unsaved(actor: Actor, agent_key: str, name: str, budget: int) -> dict[tuple[str, str], Definition]:
    """The check pack's definitions, built in memory and never published. Each is keyed in the org's own
    namespace (422 otherwise, before any run starts): `build_snapshot` pins nothing else at version 0."""
    check = check_pack_key(actor.org_id)
    with db.connect() as conn:
        ctx = studio._context(conn, actor.org_id)
    draft = _check_draft(agent_key, name, budget)
    definitions = build.pack_definitions(check, studio._org(actor), draft, ctx.tools, ctx.agents, 1)
    unsaved = {
        (d.kind, d.key): Definition(kind=d.kind, key=d.key, body=FREE_INPUT, path=d.path)
        if d.kind == "schema" and d.key == build.input_key(check)
        else d
        for d in definitions
    }
    if outside := sorted(f"{k}/{key}" for k, key in unsaved if not owners.in_org(key, actor.org_id)):
        raise ApiProblem(422, "INVALID_DEFINITION", f"The check cannot use {', '.join(outside)}.")
    return unsaved


def _agent_check_run(actor: Actor, agent_key: str, name: str, body: SubmitListingRequest) -> str:
    """Start the agent's sandbox call: the check pack runs as a sandbox test (no fees, not routed through the
    org's connections) and calls the agent through the agent runtime on sandbox data. The input is checked
    (its size cap included, 422 INVALID_INPUT) before anything starts."""
    check = check_pack_key(actor.org_id)
    inp = real_runs.check_input(check, body.input, FREE_INPUT)
    budget = body.budget_minor or CHECK_BUDGET_MINOR
    unsaved = _unsaved(actor, agent_key, name, budget)
    request = StartRunRequest(pack_slug=check, input=inp, budget_minor=budget)
    run = real_runs.start_real_run(
        request, actor, None, inp, sandbox_test=True, listing_check=True, unsaved=unsaved
    )
    return run.id


def _sandbox_check(
    actor: Actor, kind: Kind, key: str, checked: _Checked, body: SubmitListingRequest
) -> tuple[str, str, dict]:
    """(the sandbox run, the version's status, its sandbox check): a completed test of this version is reused,
    otherwise a new sandbox run starts and the version waits in `checking`. The body's input meets the size
    cap on every path (422 INVALID_INPUT), even when the reused test's own input is what is recorded."""
    if checked.reused:
        real_runs.check_input(key, body.input, None)
        run_id = checked.reused["id"]
        check = {"name": "sandbox", "state": "passed", "detail": SANDBOX_REUSED, "run_id": run_id}
        return run_id, "in_review", check
    _sandbox_ready(actor)
    if kind == "pack":
        budget = {"budget_minor": body.budget_minor} if body.budget_minor else {}
        test = SandboxRunRequest(input=body.input, **budget)
        run_id = studio.sandbox_run(actor, key, test, listing_check=True).id
    else:
        run_id = _agent_check_run(actor, key, checked.name, body)
    return (
        run_id,
        "checking",
        {"name": "sandbox", "state": "running", "detail": SANDBOX_RUNNING, "run_id": run_id},
    )


def _checked_run_input(conn, run_id: str, kind: str, key: str, version: int) -> dict:
    """The sandbox run's own input, once the run is known to have pinned the version being recorded. 409
    VERSION_CONFLICT when the definition was saved again as the check started, so the run tested another
    version."""
    row = conn.execute(
        "SELECT input FROM runs WHERE id = %s AND snapshot->'versions' @> %s",
        (run_id, _pinned(kind, key, version)),
    ).fetchone()
    if row is None:
        raise ApiProblem(
            409, "VERSION_CONFLICT", "This was saved again while its checks started. Submit the new version."
        )
    return row["input"]


def submit(actor: Actor, kind: Kind, key: str, body: SubmitListingRequest) -> str:
    """Check and submit the saved version of the org's own agent or pack; returns the listing id."""
    checked = _check(actor, kind, key)
    run_id, status, sandbox = _sandbox_check(actor, kind, key, checked, body)
    with db.connect() as conn:
        check_input = _checked_run_input(conn, run_id, kind, key, checked.saved.version)
        bundle = (
            _agent_bundle(conn, actor.org_id, key, checked.saved, run_id)
            if kind == "agent"
            else checked.bundle
        )
        try:
            listing_id, _ = listings.submit(
                conn,
                kind=kind,
                key=key,
                publisher_org_id=actor.org_id,
                name=checked.name,
                definition_version=checked.saved.version,
                definitions=bundle,
                price_minor=body.price_minor,
                checks=[*checked.checks, sandbox],
                status=status,
                submitted_by=actor.email or actor.user_id,
                check_run_id=run_id,
                check_input=check_input,
            )
        except listings.SubmissionOpen as exc:
            raise ApiProblem(409, "SUBMISSION_OPEN", str(exc)) from None
        except listings.Transition:  # not the workspace's private definition
            raise _not_found(kind, key) from None
        except ValueError as exc:
            if LISTED_ELSEWHERE not in str(exc):
                raise
            raise _not_found(kind, key) from None
        conn.commit()
    return listing_id
