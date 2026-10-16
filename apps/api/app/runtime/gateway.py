"""Tool Gateway: every tool call goes policy -> driver. The policy is a built-in rules engine behind
`decide`, so a Cerbos policy decision point can replace it later without touching callers."""

from dataclasses import dataclass

from jsonschema import Draft202012Validator

from app.runtime import routes
from app.runtime.drivers import (
    META_TOOL_PREFIX,
    ComposioDriver,
    McpDriver,
    RouteChangedDriver,
    SandboxDriver,
    ToolResult,
    UnconnectedDriver,
    driver_for,
)

PERMIT, DENY, REQUIRE_APPROVAL = "PERMIT", "DENY", "REQUIRE_APPROVAL"
DEFAULT_POLICY_REF = "policy/default"
# Reason codes of a live-workspace call that cannot run (`approval_refusal`; the call itself fails with
# GRANT_REVOKED as its policy reason, or with the NotConnected / RouteChanged driver errors).
GRANT_REVOKED = "GRANT_REVOKED"  # the org's connection does not grant the pack the tool's capability
NOT_CONNECTED = "NOT_CONNECTED"  # the app has no usable connection
ROUTE_CHANGED = "ROUTE_CHANGED"  # the app was reconnected another way since the run started

Driver = SandboxDriver | ComposioDriver | McpDriver | UnconnectedDriver | RouteChangedDriver


@dataclass
class PolicyDecision:
    verdict: str  # PERMIT | DENY | REQUIRE_APPROVAL
    reason_codes: list[str]
    ref: str


def decide(
    *,
    tool: dict,
    connector_key: str,
    contract: dict,
    overrides: dict[str, dict],
    disabled: set[str],
    approved: bool,
) -> PolicyDecision:
    """Decide one tool call.

    `tool` is the connector tool definition; its connector's per-class `defaults` are read from
    `tool["defaults"]` (call_tool adds them). Ops `overrides[connector_key]` win over those defaults.
    """
    authorization = contract.get("authorization") or {}
    ref = authorization.get("policy_ref") or DEFAULT_POLICY_REF

    def verdict(v: str, code: str) -> PolicyDecision:
        return PolicyDecision(verdict=v, reason_codes=[code], ref=ref)

    if connector_key in disabled:
        return verdict(DENY, "CONNECTOR_DISABLED")
    if tool.get("capability") not in (authorization.get("tool_capabilities") or []):
        return verdict(DENY, "CAPABILITY_NOT_IN_CONTRACT")
    classes = {**(tool.get("defaults") or {}), **(overrides.get(connector_key) or {})}
    decision = classes.get(tool.get("action_class"), "deny")  # an unknown class fails closed
    if decision == "permit":
        return verdict(PERMIT, "ACTION_CLASS_PERMITTED")
    if decision == "require_approval":
        return (
            verdict(PERMIT, "APPROVAL_GRANTED")
            if approved
            else verdict(REQUIRE_APPROVAL, "APPROVAL_REQUIRED")
        )
    return verdict(DENY, "ACTION_CLASS_DENIED")


def contract_of(snapshot: dict) -> dict:
    contracts = (snapshot.get("defs") or {}).get("contract") or {}
    workflows = (snapshot.get("defs") or {}).get("workflow") or {}
    refs = [w["body"].get("work_contract_ref") for w in workflows.values()]
    if len(refs) == 1 and refs[0] in contracts:
        return contracts[refs[0]]["body"]
    if len(contracts) == 1:
        return next(iter(contracts.values()))["body"]
    raise LookupError("snapshot does not pin exactly one work contract")


def find_tool(snapshot: dict, tool_ref: str) -> tuple[str, dict, dict] | None:
    """Resolve "<connector>.<tool id>" to (connector key, connector body, tool definition)."""
    connector_key, _, tool_id = tool_ref.partition(".")
    connector = ((snapshot.get("defs") or {}).get("connector") or {}).get(connector_key)
    if connector is None:
        return None
    body = connector["body"]
    tool = next((t for t in body.get("tools") or [] if t.get("id") == tool_id), None)
    if tool is None or str(tool.get("slug", "")).upper().startswith(META_TOOL_PREFIX):
        return None
    return connector_key, body, tool


def _org_routed(snapshot: dict) -> bool:
    return snapshot.get("routing") == routes.ORG_ROUTING


def _pack_key(snapshot: dict) -> str | None:
    """The key of the pack a run pins (a run snapshot pins exactly one), for its own sandbox data."""
    packs = list((snapshot.get("defs") or {}).get("pack") or {})
    return packs[0] if len(packs) == 1 else None


def _route_driver(snapshot: dict, connector_key: str, connector: dict, route: routes.Route) -> Driver:
    """The driver a live-workspace run's route gives: nothing runs for an app with no usable connection, or
    for one whose route is not the one pinned when the run started."""
    if route.mode == "none":
        return UnconnectedDriver()
    if routes.route_changed(snapshot, connector_key, route):
        return RouteChangedDriver(str(connector.get("app") or connector_key))
    if route.mode == "mcp":
        # If the route and the pinned connector name different servers, fail closed.
        if not route.account_id or connector.get("server") != route.account_id:
            return UnconnectedDriver()
        return McpDriver(route.account_id, org_id=str(snapshot.get("org_id") or ""))
    if route.mode == "composio":
        return ComposioDriver(user_id=route.user_id, account_id=route.account_id)
    return SandboxDriver(pack=_pack_key(snapshot))


def _route(snapshot: dict, connector_key: str) -> routes.Route:
    return routes.current_route(snapshot.get("org_id"), connector_key)


def _mode_of(snapshot: dict, mode: str) -> str:
    """The connector mode of an un-routed run: the one its snapshot pins (a Studio sandbox test pins
    "sandbox", so it answers from sandbox data whatever the worker's own mode), else the worker's `mode`."""
    return str(snapshot.get("connector_mode") or mode)


def driver_of(snapshot: dict, connector_key: str, connector: dict, mode: str) -> Driver:
    """The driver for one call. A live-workspace run (`routing: org`) follows the org's connection row for the
    app now (`routes.current_route`); any other run keeps the connector mode its snapshot pins, else `mode`
    (the worker's NM_CONNECTOR_MODE)."""
    if not _org_routed(snapshot):
        return driver_for(connector, _mode_of(snapshot, mode), pack=_pack_key(snapshot))
    return _route_driver(snapshot, connector_key, connector, _route(snapshot, connector_key))


def runs_simulated(snapshot: dict, tool_ref: str, mode: str) -> bool:
    """Whether a call to `tool_ref` would run against sandbox data: by the org's connection for a live run,
    else by the connector mode the snapshot pins (a sandbox test) or the worker's `mode` ("auto" checks the
    connection now). A forecast: the call itself checks again."""
    found = find_tool(snapshot, tool_ref)
    return found is not None and isinstance(driver_of(snapshot, found[0], found[1], mode), SandboxDriver)


def _install_of(snapshot: dict) -> str | None:
    """The name grants know the run's pack by (as `live_connections.pack_grants` writes it), or None when the
    snapshot does not pin exactly one pack."""
    packs = (snapshot.get("defs") or {}).get("pack") or {}
    if len(packs) != 1:
        return None
    key, item = next(iter(packs.items()))
    body = item.get("body") or {}
    return str(body.get("name") or body.get("slug") or key)


def _granted(snapshot: dict, route: routes.Route, tool: dict) -> bool:
    """Whether the org's (usable) connection grants the run's pack this tool's capability (see `_refusal`)."""
    install = _install_of(snapshot)
    return install is not None and route.allows(install, str(tool.get("capability") or ""))


def approval_refusal(snapshot: dict, tool_ref: str) -> str | None:
    """The reason code a live-workspace call to `tool_ref` could not run for now, else None: the app has no
    usable connection (NOT_CONNECTED), it was reconnected another way since the run started (ROUTE_CHANGED),
    or its connection no longer grants the pack the tool's capability (GRANT_REVOKED). Approvals ask this
    before they open, so nobody is asked to approve a call that will fail. A forecast: the call itself checks
    again. Demo runs (no `routing` mark) and unknown tools are never refused here."""
    found = find_tool(snapshot, tool_ref)
    if found is None or not _org_routed(snapshot):
        return None
    connector_key, _, tool = found
    return _refusal(snapshot, connector_key, route=_route(snapshot, connector_key), tool=tool)


def _refusal(snapshot: dict, connector_key: str, *, route: routes.Route, tool: dict) -> str | None:
    """Why a live-workspace call on `route` could not run, in one order for the forecast and the call:
    NOT_CONNECTED, then ROUTE_CHANGED, then GRANT_REVOKED; None when it can run."""
    if route.mode == "none":
        return NOT_CONNECTED
    if routes.route_changed(snapshot, connector_key, route):
        return ROUTE_CHANGED
    return None if _granted(snapshot, route, tool) else GRANT_REVOKED


def _argument_errors(tool: dict, args: dict) -> list[str]:
    schema = tool.get("input_schema") or {"type": "object"}
    return [e.message for e in Draft202012Validator(schema).iter_errors(args)]


def call_tool(
    *, snapshot: dict, tool_ref: str, args: dict, approved: bool, mode: str
) -> tuple[PolicyDecision, ToolResult | None]:
    """Policy first; only a PERMIT reaches a driver. Returns (decision, result or None when not executed).

    A live-workspace run reads the app's route once, after the Ops and contract policy: a usable connection
    must grant the pack the tool's capability (else DENY GRANT_REVOKED, also for a call that would need
    approval), and the same route picks the driver. An approval node asks `approval_refusal` before it
    opens."""
    contract = contract_of(snapshot)
    found = find_tool(snapshot, tool_ref)
    if found is None:
        ref = (contract.get("authorization") or {}).get("policy_ref") or DEFAULT_POLICY_REF
        return PolicyDecision(verdict=DENY, reason_codes=["UNKNOWN_TOOL"], ref=ref), None
    connector_key, connector, tool = found
    decision = decide(
        tool={**tool, "defaults": connector.get("defaults") or {}},
        connector_key=connector_key,
        contract=contract,
        overrides=snapshot.get("overrides") or {},
        disabled=set(snapshot.get("disabled") or []),
        approved=approved,
    )
    if decision.verdict == DENY:
        return decision, None
    route = _route(snapshot, connector_key) if _org_routed(snapshot) else None
    # A call that is not connected, or whose route changed, fails at its driver (NotConnected, RouteChanged)
    # with the same precedence `approval_refusal` forecasts; only a revoked grant is a policy denial.
    if route is not None and _refusal(snapshot, connector_key, route=route, tool=tool) == GRANT_REVOKED:
        return PolicyDecision(verdict=DENY, reason_codes=[GRANT_REVOKED], ref=decision.ref), None
    if decision.verdict != PERMIT:
        return decision, None
    errors = _argument_errors(tool, args)
    if errors:  # model-supplied arguments are checked before any driver sees them; nothing ran
        return decision, ToolResult(
            ok=False, data=None, mocked=False, error="invalid arguments: " + "; ".join(errors)
        )
    if route is None:
        return decision, driver_for(connector, _mode_of(snapshot, mode), pack=_pack_key(snapshot)).execute(
            connector_key, tool, args
        )
    return decision, _route_driver(snapshot, connector_key, connector, route).execute(
        connector_key, tool, args
    )
