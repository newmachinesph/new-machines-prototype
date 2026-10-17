"""The Studio (sub-project C): an org's own agents and Workflow Packs.

A draft is checked by the builder's rules (`studio_build`), then by the definition validator against
everything the org may see, and published as the org's private definitions (source "builder"). Every
function works in the caller's org: a key another org owns is answered as not found. The routes are live
workspace only.

Every key built here comes from `_free_key` or `_own`, so it is in the caller's namespace. Should
`studio_build.org_key_check` still refuse one, its ValueError (which names the org) is left to the generic
500 handler, whose reply never carries the message.
"""

import json
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace

from pydantic import ValidationError

from app import db, listings, live_connections, live_work, mcp_servers, real_runs, settings
from app import studio_build as build
from app.auth import Actor
from app.catalog.agents import market_listing
from app.defs import owners, registry
from app.defs import text as def_text
from app.defs.digest import digest
from app.defs.model import SHARED_SCHEMAS, Bundle, Definition, path_for
from app.defs.tool_names import tool_name
from app.defs.validate import validate_bundle
from app.errors import ApiProblem, ProblemIssue
from app.models.requests import StartRunRequest
from app.models.runs import Run
from app.models.studio import (
    AgentDraft,
    BuilderCheck,
    BuilderIssue,
    ImportedWorkflow,
    ImportWorkflowRequest,
    PackCopy,
    PackCopySource,
    PackDraft,
    Palette,
    PaletteAgent,
    PaletteSchema,
    PaletteSpace,
    PaletteTool,
    SandboxRunRequest,
    SaveAgentRequest,
    SavePackRequest,
    StepDraft,
    StudioAgent,
    StudioAgentSummary,
    StudioPack,
    StudioPackSummary,
    WorkflowYaml,
)
from app.runtime import routes
from app.runtime.drivers import MCP_TRANSPORT
from app.runtime.projection import TERMINAL_RUN_STATUSES

# A release's definitions and the version they replace (None for a first save): what `_save` hands a
# `before_commit` hook, which runs on the same transaction once the release is published.
BeforeCommit = Callable[[list[Definition], registry.Version | None], None]

BUILDER_ROLES = frozenset({"owner", "admin", "member"})
DRAFT_NAME = "draft"  # the provisional key a draft is validated under before it has its own
SAVE_REASON = "Saved in the Studio"
REBUILD_REASON = "Rebuilt in the Studio with its saved agent"
KEY_TRIES = 99
SUFFIX_ROOM = 4  # "-99"


def require_builder(actor: Actor) -> None:
    if actor.role not in BUILDER_ROLES:
        raise ApiProblem(
            403,
            "POLICY_DENIED",
            "Reviewers cannot build agents or packs. Ask an owner or admin to change your role.",
        )


def _org(actor: Actor) -> build.OrgRef:
    return build.OrgRef(actor.org_id, actor.org_name or "Your team")


def _who(actor: Actor) -> str:
    return actor.email or actor.user_id


def _own(conn, org_id: str, kind: str, key: str) -> registry.Version:
    """The latest version of an org's own kind/key; 404 for anything else, another org's included."""
    found = registry.latest(conn, kind, key)
    if found is None or registry.owner_of(conn, kind, key) != owners.org_owner(org_id):
        raise ApiProblem(404, "NOT_FOUND", f"Your Studio has no {kind} called {key}.")
    return found


CHECK_NAME = "listing-check"  # reserved: a submission check runs as an unsaved pack under this key


def _free_key(conn, org_id: str, kinds: tuple[str, ...], title: str) -> str:
    """The org's first unused key for `title` across `kinds`: <namespace>--<slug>, then -2, -3 and so on.
    Call under `registry.lock`."""
    base = owners.slugify(title)
    for n in range(1, KEY_TRIES + 1):
        name = base if n == 1 else f"{base[: owners.NAME_MAX - SUFFIX_ROOM].rstrip('-')}-{n}"
        key = owners.org_key(org_id, name)
        if name == CHECK_NAME:  # the listing check's pack key (see `listing_checks`)
            continue
        unused = all(
            registry.latest(conn, k, key) is None and registry.owner_of(conn, k, key) == owners.PLATFORM
            for k in kinds
        )
        if unused:
            return key
    raise ApiProblem(409, "KEY_TAKEN", "Too many items have this name. Choose another name.")


def _invalid(issues: list[BuilderIssue]) -> ApiProblem:
    return ApiProblem(
        422,
        "INVALID_DEFINITION",
        f"{len(issues)} problem(s); first: {issues[0].message}",
        [ProblemIssue(kind="studio", key=i.step or "", path=i.path, message=i.message) for i in issues],
    )


def _validator_issues(bundle: Bundle, defs: list[Definition], key: str) -> list[BuilderIssue]:
    """The definition validator's errors in `defs`, checked with everything else the org may see."""
    items = {**bundle.items, **{(d.kind, d.key): d for d in defs}}
    mine = {(d.kind, d.key) for d in defs}
    return [build.issue_of(e, key) for e in validate_bundle(Bundle(items=items)) if (e.kind, e.key) in mine]


def _unchanged(conn, defs: list[Definition]) -> bool:
    for d in defs:
        current = registry.latest(conn, d.kind, d.key)
        if current is None or current.digest != digest(d):
            return False
    return True


def _save(
    conn,
    actor: Actor,
    kind: str,
    key: str,
    build_release: Callable[[int], list[Definition]],
    base_version: int | None,
    before_commit: BeforeCommit | None = None,
) -> None:
    """Publish the release of kind/key that `build_release(release)` makes as the org's own definitions, and
    commit. When the current release rebuilt is unchanged nothing is published. 409 VERSION_CONFLICT when
    `base_version` is not the latest version; 409 KEY_TAKEN when a key belongs to someone else.
    `before_commit(defs, replaced)` runs after the publish, in the same transaction."""
    registry.lock(conn)
    current = registry.latest(conn, kind, key)
    now = current.version if current else 0
    if base_version is not None and base_version != now:
        raise ApiProblem(
            409,
            "VERSION_CONFLICT",
            f"Version {now} was saved since you opened version {base_version}. Copy your changes, reload and "
            "apply them again.",
        )
    if current is not None and _unchanged(conn, build_release(now)):
        return
    owner, who = owners.org_owner(actor.org_id), _who(actor)
    defs = build_release(now + 1)
    try:
        for d in defs:
            registry.claim(conn, d.kind, d.key, owner, who)
    except registry.KeyTaken:
        raise ApiProblem(409, "KEY_TAKEN", f"{key} belongs to someone else. Choose another name.") from None
    for d in defs:
        registry.publish_if_changed(conn, d, who, SAVE_REASON, source=registry.BUILDER)
    if before_commit is not None:
        before_commit(defs, current)
    conn.commit()


def _is_own_or_platform(key: str, org_id: str, listed: Collection[str] = ()) -> bool:
    """A key an org's pack may use: the platform's (no namespace), the org's own, or an agent another
    workspace has listed (at its approved version). Another org's private key is never offered or built
    with."""
    return not owners.is_reserved(key) or owners.in_org(key, org_id) or key in listed


@dataclass(frozen=True)
class _Context:
    """What the org may build with: everything it may see, indexed. `agents` holds the platform's, the org's
    own and other workspaces' listed agents (`listed`, by key), so another org's private agent key is missing
    to a pack draft. `spaces` and `schemas` hold the platform's and the org's own only: a listed bundle's
    memory spaces and schemas are what its own agent runs with, never what a buyer's steps are built with."""

    bundle: Bundle
    tools: dict[str, dict]
    agents: dict[str, dict]
    spaces: dict[str, Definition]
    schemas: dict[str, Definition]
    team: set[tuple[str, str]]
    listed: dict[str, listings.MarketRow]
    pack_names: dict[str, str]  # {key: name} of the org's own packs and the packs it added


def _taken_pack_names(conn, org_id: str) -> dict[str, str]:
    """{key: name} of the packs a draft's name must not repeat: the org's own and the packs it added, the
    names its connection grants are keyed by. Another workspace's listed pack the org has not added holds no
    grants, so its name never blocks a save."""
    names = {v.key: str(v.body.get("name") or v.key) for v in registry.owned(conn, org_id, "pack")}
    return {**live_connections.added_names(conn, org_id), **names}


def _context(conn, org_id: str) -> _Context:
    bundle = registry.visible_bundle(conn, org_id)
    market = listings.market_info(conn, org_id)
    listed = {key: row for (kind, key), row in market.items() if kind == "agent"}
    servers = mcp_servers.live_server_ids(conn, org_id)
    return _Context(
        bundle=bundle,
        # A removed MCP server's tools are not offered, so a save reports them as unknown tools.
        tools={ref: t for ref, t in build.tool_index(bundle).items() if _offered(bundle, ref, servers)},
        agents={d.key: d.body for d in bundle.of("agent") if _is_own_or_platform(d.key, org_id, listed)},
        spaces={d.key: d for d in build.readable_spaces(bundle) if _is_own_or_platform(d.key, org_id)},
        schemas={d.key: d for d in bundle.of("schema") if _is_own_or_platform(d.key, org_id)},
        team=registry.team_keys(conn, org_id),
        listed=listed,
        pack_names=_taken_pack_names(conn, org_id),
    )


# --- palette ------------------------------------------------------------------------------------------------


def _palette_agent(d: Definition, ctx: _Context) -> PaletteAgent:
    out_ref = str(d.body.get("output_schema_ref") or "")
    out = ctx.schemas.get(out_ref) or ctx.bundle.get("schema", out_ref)  # a listed agent's own result shape
    return PaletteAgent(
        key=d.key,
        name=str(d.body.get("name") or d.key),
        summary=str(d.body.get("summary") or ""),
        built_by_team=True if ("agent", d.key) in ctx.team else None,
        model_profile=(d.body.get("runtime") or {}).get("model_profile"),
        output_schema_ref=out_ref,
        output_schema=out.body if out else None,
        listing=market_listing(ctx.listed[d.key], "call", None) if d.key in ctx.listed else None,
    )


def _offered(bundle, ref: str, servers: set[str]) -> bool:
    """A tool of an org's own MCP server is offered only while its server is not removed."""
    connector = bundle.get("connector", ref.partition(".")[0])
    body = connector.body if connector is not None else {}
    return body.get("transport") != MCP_TRANSPORT or body.get("server") in servers


def palette(actor: Actor) -> Palette:
    """Everything a pack's steps can use, from the registry: a new agent or app tool shows up by itself. The
    agents are the ones a draft may use (`_Context.agents`): the platform's, the org's own and other
    workspaces' listed ones, with their listing. An org's own MCP server's tools are labelled with the
    server's name, while it is connected."""
    with db.connect() as conn:
        ctx = _context(conn, actor.org_id)
    return Palette(
        agents=[_palette_agent(d, ctx) for d in ctx.bundle.of("agent") if d.key in ctx.agents],
        tools=[
            PaletteTool(
                ref=ref,
                app=t["app"],
                name=tool_name(t),
                description=str(t.get("description") or ""),
                action_class=t["action_class"],
                capability=t["capability"],
                input_schema=t.get("input_schema") or {},
            )
            for ref, t in sorted(ctx.tools.items())
        ],
        spaces=[
            PaletteSpace(key=k, name=str(d.body.get("name") or k)) for k, d in sorted(ctx.spaces.items())
        ],
        schemas=[
            PaletteSchema(key=k, title=str(d.body.get("title") or k), body=d.body)
            for k, d in sorted(ctx.schemas.items())
            if k.startswith(f"{SHARED_SCHEMAS}/")
        ],
    )


# --- agents -------------------------------------------------------------------------------------------------


def _agent(conn, org_id: str, key: str) -> StudioAgent:
    v = _own(conn, org_id, "agent", key)
    return StudioAgent(
        key=key,
        version=v.version,
        published_at=v.published_at,
        published_by=v.published_by,
        draft=build.agent_draft(v.body, v.files),
    )


def _agent_issues(ctx: _Context, key: str, org: build.OrgRef, draft: AgentDraft) -> list[BuilderIssue]:
    issues = build.agent_issues(draft, ctx.tools)
    if issues:
        return issues
    return _validator_issues(ctx.bundle, [build.agent_definition(key, org, draft, ctx.tools, 1)], key)


def _checked_agent(conn, actor: Actor, key: str, draft: AgentDraft) -> tuple[_Context, build.OrgRef]:
    """The context the draft was checked in; 422 INVALID_DEFINITION with its issues otherwise."""
    ctx, org = _context(conn, actor.org_id), _org(actor)
    if issues := _agent_issues(ctx, key, org, draft):
        raise _invalid(issues)
    return ctx, org


def _save_agent(
    conn,
    actor: Actor,
    ctx: _Context,
    org: build.OrgRef,
    key: str,
    draft: AgentDraft,
    base: int | None,
    before_commit: BeforeCommit | None = None,
) -> StudioAgent:
    _save(
        conn,
        actor,
        "agent",
        key,
        lambda r: [build.agent_definition(key, org, draft, ctx.tools, r)],
        base,
        before_commit=before_commit,
    )
    return _agent(conn, actor.org_id, key)


def _packs_using(conn, org_id: str, agent_key: str) -> list[registry.Version]:
    """The latest version of each pack the org owns whose agents list `agent_key`."""
    return [v for v in registry.owned(conn, org_id, "pack") if agent_key in (v.body.get("agents") or [])]


def _broken_pack(name: str, issues: list[BuilderIssue]) -> ApiProblem:
    """422 INVALID_DEFINITION: saving the agent would leave the pack `name` with `issues`."""
    return ApiProblem(
        422,
        "INVALID_DEFINITION",
        f"{name} would not work with this agent; first: {issues[0].message}",
        [ProblemIssue(kind="pack", key=name, path=i.path, message=i.message) for i in issues],
    )


def _rebuild_packs(
    conn, actor: Actor, ctx: _Context, org: build.OrgRef, key: str, defs: list[Definition]
) -> None:
    """The org's packs that use the agent follow its save: each is rebuilt with the new agent body, so its
    contract covers the agent's tools and its connectors list their apps, published when that changed it,
    and re-granted (`_regrant`; the name is unchanged, so no run holds it up). Runs in the save's
    transaction, under the registry lock. A pack the new agent would leave with problems refuses the whole
    save (422, naming the pack): a broken pack is never published."""
    agent = next(d for d in defs if d.kind == "agent")
    rebuilt = replace(ctx, agents={**ctx.agents, key: agent.body})
    bundle = Bundle(items={**ctx.bundle.items, (agent.kind, agent.key): agent})
    for v in _packs_using(conn, actor.org_id, key):
        draft = _pack(conn, actor.org_id, v.key).draft
        name = str(v.body.get("name") or v.key)
        issues = build.pack_issues(
            draft, ctx.tools, rebuilt.agents, set(ctx.spaces), set(ctx.schemas), names=_pack_names(ctx, v.key)
        )
        if issues:
            raise _broken_pack(name, issues)
        current = _pack_release(rebuilt, v.key, org, draft, v.version)
        if issues := _validator_issues(bundle, current, v.key):
            raise _broken_pack(name, issues)
        if _unchanged(conn, current):
            continue
        release = _pack_release(rebuilt, v.key, org, draft, v.version + 1)
        for d in release:
            registry.publish_if_changed(conn, d, _who(actor), REBUILD_REASON, source=registry.BUILDER)
        _regrant(conn, ctx, actor.org_id, v.key, release, v)


def list_agents(actor: Actor) -> list[StudioAgentSummary]:
    """The org's own agents, each with the packs (that the org may see) using it."""
    with db.connect() as conn:
        mine = registry.owned(conn, actor.org_id, "agent")
        packs = [v for v in registry.latest_visible(conn, actor.org_id) if v.kind == "pack"]
    return [
        StudioAgentSummary(
            key=v.key,
            name=str(v.body.get("name") or v.key),
            summary=str(v.body.get("summary") or ""),
            model_profile=str((v.body.get("runtime") or {}).get("model_profile") or ""),
            version=v.version,
            published_at=v.published_at,
            used_by=sorted(
                str(p.body.get("name") or p.key) for p in packs if v.key in (p.body.get("agents") or [])
            ),
        )
        for v in mine
    ]


def get_agent(actor: Actor, key: str) -> StudioAgent:
    with db.connect() as conn:
        return _agent(conn, actor.org_id, key)


def validate_agent(actor: Actor, draft: AgentDraft) -> BuilderCheck:
    """Check a draft without saving it."""
    require_builder(actor)
    with db.connect() as conn:
        ctx = _context(conn, actor.org_id)
    issues = _agent_issues(ctx, owners.org_key(actor.org_id, DRAFT_NAME), _org(actor), draft)
    return BuilderCheck(ok=not issues, issues=issues)


def create_agent(actor: Actor, draft: AgentDraft) -> StudioAgent:
    """Save a new agent as version 1 under a key made from its name. The draft is checked under the
    provisional key before the registry lock is taken, so the lock covers only picking the key and saving."""
    require_builder(actor)
    with db.connect() as conn:
        ctx, org = _checked_agent(conn, actor, owners.org_key(actor.org_id, DRAFT_NAME), draft)
        registry.lock(conn)
        key = _free_key(conn, actor.org_id, ("agent",), draft.name)
        return _save_agent(conn, actor, ctx, org, key, draft, None)


def save_agent(actor: Actor, key: str, body: SaveAgentRequest) -> StudioAgent:
    """Save the draft as the agent's next version (nothing new when it is unchanged). The org's packs that
    use the agent are rebuilt and re-granted with it in the same save (`_rebuild_packs`); 422 names a pack
    the change would break."""
    require_builder(actor)
    with db.connect() as conn:
        _own(conn, actor.org_id, "agent", key)
        ctx, org = _checked_agent(conn, actor, key, body.draft)
        return _save_agent(
            conn,
            actor,
            ctx,
            org,
            key,
            body.draft,
            body.base_version,
            before_commit=lambda defs, replaced: _rebuild_packs(conn, actor, ctx, org, key, defs),
        )


# --- packs --------------------------------------------------------------------------------------------------

PACK_KINDS = ("pack", "workflow", "contract")
# A step's outcomes that mean the step did not succeed: an imported workflow that leaves them unrouted sends
# them to its FAILED end, which is what every seed workflow means by them.
FAILURE_OUTCOMES = frozenset({"denied", "error", "rejected", "timeout", "fail"})


def _added(conn, org_id: str) -> set[str]:
    rows = conn.execute("SELECT pack_slug FROM installations WHERE org_id = %s", (org_id,)).fetchall()
    return {r["pack_slug"] for r in rows}


def _pack_release(
    ctx: _Context, key: str, org: build.OrgRef, draft: PackDraft, release: int
) -> list[Definition]:
    used = {str(s.config.get("agent")) for s in draft.steps if s.type == "agent"}
    if not used <= set(ctx.agents):  # `_context` never offers another; a backstop
        raise ValueError("a pack is built only with agents the org may use")
    return build.pack_definitions(key, org, draft, ctx.tools, ctx.agents, release)


def _pack_names(ctx: _Context, key: str) -> list[str]:
    """The names of the org's own and added packs, minus the pack's own: a draft must not repeat one, as
    connection grants are keyed by pack name."""
    return [name for k, name in ctx.pack_names.items() if k != key]


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _evaluator_issues(ctx: _Context, org_id: str, draft: PackDraft) -> list[BuilderIssue]:
    """A builder keeps a decision's model setup (`evaluator`) but never writes one: it must equal that of a
    decision the platform or the org itself has."""
    known = {
        _canonical(d.body["evaluator"])
        for d in ctx.bundle.of("decision_rules")
        if d.body.get("evaluator") and _is_own_or_platform(d.key, org_id)
    }
    return [
        BuilderIssue(
            path=f"steps.{s.id}.rules.evaluator",
            message=(
                "This step's decision model setup can only come from a ready-made pack or one of your own."
            ),
            step=s.id,
        )
        for s in draft.steps
        if s.rules is not None and s.rules.evaluator and _canonical(s.rules.evaluator) not in known
    ]


def _pack_issues(ctx: _Context, key: str, org: build.OrgRef, draft: PackDraft) -> list[BuilderIssue]:
    issues = build.pack_issues(
        draft, ctx.tools, ctx.agents, set(ctx.spaces), set(ctx.schemas), names=_pack_names(ctx, key)
    )
    issues += _evaluator_issues(ctx, org.id, draft)
    if issues:
        return issues
    return _validator_issues(ctx.bundle, _pack_release(ctx, key, org, draft, 1), key)


def _pack(conn, org_id: str, key: str) -> StudioPack:
    v = _own(conn, org_id, "pack", key)
    workflow = registry.latest(conn, "workflow", v.body["workflow"]).body
    contract = registry.latest(conn, "contract", v.body["contract"]).body
    schema = registry.latest(conn, "schema", contract["input_schema_ref"])
    rules = {}
    for node in workflow["nodes"]:
        if node["type"] == "decision":
            found = registry.latest(conn, "decision_rules", node["config"]["rules"])
            if found is not None:
                rules[node["id"]] = found.body
    return StudioPack(
        key=key,
        version=v.version,
        published_at=v.published_at,
        published_by=v.published_by,
        draft=build.pack_draft(v.body, workflow, contract, schema.body if schema else {}, rules),
        added=key in _added(conn, org_id),
    )


def _no_runs_in_progress(conn, org_id: str, key: str) -> None:
    """409 RUNS_IN_PROGRESS while the org has an org-routed run of the pack that is not over: such a run reads
    the pack's name from its pinned snapshot to find its grants, so renaming them would leave it with none.
    A sandbox test (un-routed, never reads grants) does not count. Under the installations row lock, which a
    start holds shared while it pins, so a run that starts after this check pins the new name."""
    terminal = sorted(TERMINAL_RUN_STATUSES)
    row = conn.execute(
        "SELECT count(*) AS n FROM runs WHERE org_id = %s AND pack_slug = %s AND status <> ALL(%s) "
        "AND snapshot->>'routing' = %s",
        (org_id, key, terminal, routes.ORG_ROUTING),
    ).fetchone()
    n = int(row["n"]) if row else 0
    if n == 0:
        return
    which = "the run" if n == 1 else f"the {n} runs"
    raise ApiProblem(
        409, "RUNS_IN_PROGRESS", f"Finish or cancel {which} of this pack in progress before renaming it."
    )


def _regrant(
    conn, ctx: _Context, org_id: str, key: str, defs: list[Definition], replaced: registry.Version | None
) -> None:
    """A pack the org has added keeps its connection grants in step with the save: the grants (and the ones a
    person revoked) follow a new name, the apps the new release uses gain the grants its contract allows, and
    the org's installation moves to the new version. A pack the org has not added touches nothing. A rename
    waits until the org has no run of the pack in progress (409 RUNS_IN_PROGRESS), as a run finds its grants
    by the name its snapshot pinned."""
    row = conn.execute(
        "SELECT pack_version FROM installations WHERE org_id = %s AND pack_slug = %s FOR UPDATE",
        (org_id, key),
    ).fetchone()
    if row is None:
        return
    pack = next(d.body for d in defs if d.kind == "pack")
    contracts = {d.key: d.body for d in defs if d.kind == "contract"}
    connectors = {d.key: d.body for d in ctx.bundle.of("connector")}
    new = str(pack.get("name") or key)
    if replaced is not None and (old := str(replaced.body.get("name") or key)) != new:
        _no_runs_in_progress(conn, org_id, key)
        was = {str(c) for c in replaced.body.get("connectors") or []}
        for app in sorted(was | {str(c) for c in pack.get("connectors") or []}):
            live_connections.rename_install(conn, org_id, app, old, new)
    live_connections.grant_pack(conn, connectors, org_id, pack, contracts)
    latest = registry.latest(conn, "pack", key)
    conn.execute(
        "UPDATE installations SET pack_version = %s WHERE org_id = %s AND pack_slug = %s",
        (latest.version if latest else row["pack_version"], org_id, key),
    )


def _checked_pack(conn, actor: Actor, key: str, draft: PackDraft) -> tuple[_Context, build.OrgRef]:
    """The context the draft was checked in; 422 INVALID_DEFINITION with its issues otherwise."""
    ctx, org = _context(conn, actor.org_id), _org(actor)
    if issues := _pack_issues(ctx, key, org, draft):
        raise _invalid(issues)
    return ctx, org


def _check_pack_name(conn, org_id: str, key: str, draft: PackDraft) -> None:
    """The name check again, under `registry.lock`, against what the org can see now: two saves at once
    both pass the check made before the lock, and the second must not land a second pack with the name."""
    taken = _taken_pack_names(conn, org_id)
    names = {name.strip().casefold() for k, name in taken.items() if k != key}
    if draft.name.strip().casefold() in names:
        name = draft.name.strip()
        message = f"Another pack is already called {name}. Give this one a different name."
        raise _invalid([BuilderIssue(path="name", message=message)])


def _save_pack(
    conn, actor: Actor, ctx: _Context, org: build.OrgRef, key: str, draft: PackDraft, base: int | None
) -> StudioPack:
    def build_release(release: int) -> list[Definition]:
        _check_pack_name(conn, actor.org_id, key, draft)  # runs under the registry lock
        return _pack_release(ctx, key, org, draft, release)

    _save(
        conn,
        actor,
        "pack",
        key,
        build_release,
        base,
        before_commit=lambda defs, replaced: _regrant(conn, ctx, actor.org_id, key, defs, replaced),
    )
    return _pack(conn, actor.org_id, key)


def list_packs(actor: Actor) -> list[StudioPackSummary]:
    """The packs the org built, with their step counts and whether the org has added them."""
    with db.connect() as conn:
        added = _added(conn, actor.org_id)
        workflows = {v.key: v.body for v in registry.owned(conn, actor.org_id, "workflow")}
        packs = registry.owned(conn, actor.org_id, "pack")
    return [
        StudioPackSummary(
            key=v.key,
            name=str(v.body.get("name") or v.key),
            outcome=str(v.body.get("outcome") or ""),
            version=v.version,
            published_at=v.published_at,
            steps=len((workflows.get(str(v.body.get("workflow"))) or {}).get("nodes") or []),
            added=v.key in added,
        )
        for v in packs
    ]


def get_pack(actor: Actor, key: str) -> StudioPack:
    with db.connect() as conn:
        return _pack(conn, actor.org_id, key)


def validate_pack(actor: Actor, draft: PackDraft, key: str | None = None) -> BuilderCheck:
    """Check a pack draft without saving it: the builder's rules, then the definition validator. `key` is the
    org's own pack the draft is an edit of, so its current name is not counted against it; without one the
    draft is checked as a new pack. 404 for a key that is not the org's own."""
    require_builder(actor)
    with db.connect() as conn:
        if key is not None:
            _own(conn, actor.org_id, "pack", key)
        ctx = _context(conn, actor.org_id)
    issues = _pack_issues(ctx, key or owners.org_key(actor.org_id, DRAFT_NAME), _org(actor), draft)
    return BuilderCheck(ok=not issues, issues=issues)


def create_pack(actor: Actor, draft: PackDraft) -> StudioPack:
    """Save a new pack (version 1) under a key made from its name. It is private to the org: only its own
    marketplace lists it, as built by its team."""
    require_builder(actor)
    with db.connect() as conn:
        ctx, org = _checked_pack(conn, actor, owners.org_key(actor.org_id, DRAFT_NAME), draft)
        registry.lock(conn)
        key = _free_key(conn, actor.org_id, PACK_KINDS, draft.name)
        return _save_pack(conn, actor, ctx, org, key, draft, None)


def save_pack(actor: Actor, key: str, body: SavePackRequest) -> StudioPack:
    """Save the draft as the pack's next version (nothing new when it is unchanged)."""
    require_builder(actor)
    with db.connect() as conn:
        _own(conn, actor.org_id, "pack", key)
        ctx, org = _checked_pack(conn, actor, key, body.draft)
        return _save_pack(conn, actor, ctx, org, key, body.draft, body.base_version)


def pack_workflow_yaml(actor: Actor, key: str) -> WorkflowYaml:
    """The pack's workflow.yaml as the definition files hold it."""
    with db.connect() as conn:
        pack = _own(conn, actor.org_id, "pack", key)
        workflow = registry.latest(conn, "workflow", pack.body["workflow"])
    return WorkflowYaml(yaml=registry.export_files(workflow)[path_for("workflow", workflow.key)])


def _step_from(node, bundle: Bundle, org_id: str) -> StepDraft:
    rules = None
    if isinstance(node, dict) and node.get("type") == "decision":
        ref = str((node.get("config") or {}).get("rules") or "")
        found = bundle.get("decision_rules", ref) if _is_own_or_platform(ref, org_id) else None
        rules = build.rules_of(found.body) if found is not None else None
    return build.step_of(node, rules)


def _route_failures(steps: list[StepDraft]) -> list[StepDraft]:
    """Send each unrouted failure outcome to the workflow's FAILED end step, when it has exactly one: a seed
    workflow routes a connector's "next" only and leaves denied and error to the runtime. Without such an end
    the steps are kept as written, and the builder's checks name each outcome that goes nowhere."""
    ends = [s.id for s in steps if s.type == "end" and s.config.get("status") == "FAILED"]
    if len(ends) != 1:
        return steps
    out = []
    for s in steps:
        missing = {o: ends[0] for o in build.outcomes(s) if o in FAILURE_OUTCOMES and not s.routes.get(o)}
        out.append(s.model_copy(update={"routes": {**s.routes, **missing}}) if missing else s)
    return out


def _steps_from(nodes: list, bundle: Bundle, org_id: str) -> tuple[list[StepDraft], list[BuilderIssue]]:
    """The steps of workflow nodes, with unrouted failures sent to the FAILED end; a node that cannot be read
    is an issue, not a failure."""
    steps, issues = [], []
    for i, node in enumerate(nodes):
        try:
            steps.append(_step_from(node, bundle, org_id))
        except KeyError, TypeError, ValueError, AttributeError, ValidationError:
            issues.append(BuilderIssue(path=f"nodes[{i}]", message=f"Step {i + 1} cannot be read as a step."))
    return _route_failures(steps), issues


def import_workflow(actor: Actor, body: ImportWorkflowRequest) -> ImportedWorkflow:
    """The steps of a workflow.yaml (decision rules that are the org's own or the platform's are inlined, and
    unrouted failure outcomes go to the FAILED end). A node that cannot be read is listed in `issues`;
    422 INVALID_YAML when the text is not YAML or has no nodes."""
    require_builder(actor)
    try:
        data = def_text.parse_text("workflow", body.yaml)
    except def_text.Unparseable as exc:
        raise ApiProblem(422, "INVALID_YAML", str(exc)) from None
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ApiProblem(422, "INVALID_YAML", "The YAML has no nodes.")
    with db.connect() as conn:
        bundle = registry.visible_bundle(conn, actor.org_id)
    steps, issues = _steps_from(nodes, bundle, actor.org_id)
    entry = str(data.get("entry_node_id") or (steps[0].id if steps else ""))
    return ImportedWorkflow(entry_step=entry, steps=steps, issues=issues)


def _limit(field: str) -> int:
    """The `max_length` of a PackDraft text field."""
    return next(m.max_length for m in PackDraft.model_fields[field].metadata if hasattr(m, "max_length"))


def copy_name(name: str, taken: Collection[str]) -> str:
    """The first of "<name> (copy)", "<name> (copy 2)", ... that no pack in `taken` (names, any case) has,
    shortening `name` so the whole thing fits a pack name."""
    limit = _limit("name")
    names = {t.strip().casefold() for t in taken}
    n = 1
    while True:
        suffix = " (copy)" if n == 1 else f" (copy {n})"
        candidate = name.strip()[: limit - len(suffix)].rstrip() + suffix
        if candidate.casefold() not in names:
            return candidate
        n += 1


def _cut(text: object, field: str) -> str:
    return str(text or "")[: _limit(field)]


def copy_pack(actor: Actor, source: str) -> PackCopy:
    """An unsaved draft of a pack the org may copy: the platform's or its own. Nothing is saved; the editor
    saves it as a new pack, and `issues` holds what `:validate` finds in it. 404 for a pack the org cannot
    see, 409 NOT_COPYABLE for another publisher's, 422 NOT_EDITABLE for a pack that cannot form a draft.
    Inputs it cannot hold are left out and listed."""
    require_builder(actor)
    with db.connect() as conn:
        bundle = registry.visible_bundle(conn, actor.org_id)
        found = bundle.get("pack", source)
        if found is None:
            raise ApiProblem(404, "NOT_FOUND", f"There is no pack called {source}.")
        owner = registry.owner_of(conn, "pack", source)
        if not (owner.kind == "platform" or (owner.kind == "org" and owner.id == actor.org_id)):
            raise ApiProblem(409, "NOT_COPYABLE", "A pack from another publisher can be added, not copied.")
        version = registry.latest(conn, "pack", source)
        taken = _taken_pack_names(conn, actor.org_id).values()
        ctx = _context(conn, actor.org_id)
    pack = found.body
    workflow = bundle.get("workflow", str(pack["workflow"])).body
    contract_def = bundle.get("contract", str(workflow.get("work_contract_ref") or pack["contract"]))
    contract = contract_def.body if contract_def else {}
    schema = bundle.get("schema", str(contract.get("input_schema_ref") or ""))
    steps, issues = _steps_from(workflow.get("nodes") or [], bundle, actor.org_id)
    budget = contract.get("budget") or {}
    default_budget = PackDraft.model_fields["budget_minor"].default
    fields, field_issues = build.readable_input_fields(schema.body if schema else {}, _limit("input_fields"))
    issues = [*issues, *field_issues]
    try:
        draft = PackDraft(
            name=copy_name(str(pack.get("name") or source), taken),
            outcome=_cut(pack.get("outcome") or pack.get("name"), "outcome"),
            description=_cut(
                pack.get("description") or pack.get("outcome") or pack.get("name"), "description"
            ),
            human_review=_cut(pack.get("human_review") or "A person reviews the result.", "human_review"),
            function=_cut(pack.get("function") or PackDraft.model_fields["function"].default, "function"),
            industries=[str(i) for i in pack.get("industries") or []][:5] or ["retail-commerce"],
            input_fields=fields,
            budget_minor=min(max(int(budget.get("maximum_minor") or default_budget), 100), 100_000),
            human_budget_minor=min(max(int(budget.get("human_budget_minor") or 0), 0), 100_000),
            entry_step=str(workflow.get("entry_node_id") or (steps[0].id if steps else "start")),
            steps=steps,
        )
    except ValidationError, TypeError, ValueError:
        raise ApiProblem(422, "NOT_EDITABLE", "This pack cannot be opened in the Studio.") from None
    # The same check `:validate` runs, so a copy never reports fewer problems than the editor will.
    issues = [*issues, *_pack_issues(ctx, owners.org_key(actor.org_id, DRAFT_NAME), _org(actor), draft)]
    return PackCopy(
        draft=draft,
        issues=issues,
        source=PackCopySource(key=source, name=str(pack.get("name") or source), version=version.version),
    )


# --- sandbox test -------------------------------------------------------------------------------------------


def _test_budget(conn, pack: dict) -> int:
    """The pack's budget maximum, from the Work Contract its workflow names (else the pack's `contract`), as
    the pinned snapshot resolves it (`real_runs.input_schema` does the same); 0 when none resolves."""
    workflow = registry.latest(conn, "workflow", str(pack.get("workflow") or ""))
    key = (workflow.body if workflow else {}).get("work_contract_ref") or pack.get("contract")
    contract = registry.latest(conn, "contract", str(key or ""))
    return int(((contract.body if contract else {}).get("budget") or {}).get("maximum_minor") or 0)


def sandbox_run(actor: Actor, key: str, body: SandboxRunRequest, *, listing_check: bool = False) -> Run:
    """Start a real run of the org's own pack on sandbox data ("Test in sandbox"). The pack need not be added
    and its apps need not be connected: the run is not routed through the org's connections and pins the
    sandbox connector mode, so every tool call answers from sandbox data and nothing is billed to an app. The
    input must match the pack's input schema and the month's spend must be below the cap (a test counts
    toward it). 409 SANDBOX_UNAVAILABLE when the deployment's connectors are not in sandbox mode; 422
    BUDGET_REQUIRED when the body gives no budget and the pack sets no maximum. `listing_check` marks the run
    as the sandbox check of a submission."""
    require_builder(actor)
    if settings.connector_mode() != settings.SANDBOX_MODE:
        raise ApiProblem(
            409,
            "SANDBOX_UNAVAILABLE",
            "Test runs need the platform's sandbox connectors, which this deployment does not use.",
        )
    with db.connect() as conn:
        pack = _own(conn, actor.org_id, "pack", key)
        schema = real_runs.input_schema(conn, key)
        maximum = _test_budget(conn, pack.body)
    inp = real_runs.check_input(key, body.input, schema)
    budget = body.budget_minor or maximum
    if not budget:
        raise ApiProblem(422, "BUDGET_REQUIRED", "Set a budget for this test run.")
    live_work.check_spend(actor.org_id)
    request = StartRunRequest(pack_slug=key, input=inp, budget_minor=budget)
    return real_runs.start_real_run(request, actor, None, inp, sandbox_test=True, listing_check=listing_check)
