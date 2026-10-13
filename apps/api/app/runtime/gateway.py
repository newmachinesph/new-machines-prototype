"""Tool Gateway: every tool call goes policy -> driver. The policy is a built-in rules engine behind
`decide`, so a Cerbos policy decision point can replace it later without touching callers."""

from dataclasses import dataclass

from jsonschema import Draft202012Validator

from app.runtime.drivers import META_TOOL_PREFIX, SandboxDriver, ToolResult, driver_for

PERMIT, DENY, REQUIRE_APPROVAL = "PERMIT", "DENY", "REQUIRE_APPROVAL"
DEFAULT_POLICY_REF = "policy/default"


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


def runs_simulated(snapshot: dict, tool_ref: str, mode: str) -> bool:
    """Whether a call to `tool_ref` would run against sandbox data in connector `mode`. In "auto" this checks
    the connection now, so it is a forecast: the call itself checks again."""
    found = find_tool(snapshot, tool_ref)
    return found is not None and isinstance(driver_for(found[1], mode), SandboxDriver)


def _argument_errors(tool: dict, args: dict) -> list[str]:
    schema = tool.get("input_schema") or {"type": "object"}
    return [e.message for e in Draft202012Validator(schema).iter_errors(args)]


def call_tool(
    *, snapshot: dict, tool_ref: str, args: dict, approved: bool, mode: str
) -> tuple[PolicyDecision, ToolResult | None]:
    """Policy first; only a PERMIT reaches a driver. Returns (decision, result or None when not executed)."""
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
    if decision.verdict != PERMIT:
        return decision, None
    errors = _argument_errors(tool, args)
    if errors:  # model-supplied arguments are checked before any driver sees them; nothing ran
        return decision, ToolResult(
            ok=False, data=None, mocked=False, error="invalid arguments: " + "; ".join(errors)
        )
    return decision, driver_for(connector, mode).execute(connector_key, tool, args)
