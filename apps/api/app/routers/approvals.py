from app import db, run_tasks, settings, temporal_client, workspace
from app.auth import DEMO_ORG_ID, Actor, CurrentActor
from app.defs.tool_names import action_name
from app.errors import ApiProblem
from app.models.work import Approval, ApprovalAction, DigestRow, UnlockedAction
from app.routing import ApiRouter
from app.store import get_store, iso, locked_store

router = ApiRouter(prefix="/v1", tags=["approvals"])

# run_tasks status of an approval -> Approval.status; the decision each endpoint sends the workflow.
STATUSES = {"pending": "PENDING", "granted": "GRANTED", "denied": "DECLINED", "timeout": "EXPIRED"}
DECISIONS = {"GRANTED": "granted", "DECLINED": "denied"}
DEFAULT_POLICY_REF = "policy/default"
# The digest's policy line, in words a business user reads; the policy's id stays in `policy_ref`.
POLICY_LINE = "Your workspace's policy requires approval before this step writes to your apps."
# Who decided, when the account that did is no longer a member of the org: never the account id itself.
FORMER_MEMBER = "A former member of your workspace"
# The shared demo org has no member rows for its deciders; they are other people, not former members.
ANOTHER_PERSON = "Another person"


def decider_names(actor: Actor, rows: list[dict]) -> dict[str, str]:
    """Each decider's name (or email) by account id: the org's members among the rows' deciders, and the
    caller themselves ("You" when nothing names them, as in the demo workspace)."""
    ids = sorted({row["decided_by"] for row in rows if row["decided_by"]})
    names: dict[str, str] = {}
    if ids and settings.runtime_enabled():
        with db.connect() as conn:
            members = conn.execute(
                "SELECT user_id, name, email FROM org_members WHERE org_id = %s AND user_id = ANY(%s)",
                (actor.org_id, ids),
            ).fetchall()
        names = {m["user_id"]: m["name"] or m["email"] for m in members if m["name"] or m["email"]}
    if actor.user_id in ids and actor.user_id not in names:
        names[actor.user_id] = actor.name or actor.email or "You"
    if actor.org_id == DEMO_ORG_ID:
        for decider in ids:
            names.setdefault(decider, ANOTHER_PERSON)
    return names


def find_approval(approval_id: str) -> Approval:
    found = next((a for a in get_store().approvals if a.id == approval_id), None)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No approval {approval_id}.")
    return found


def _connector_body(row: dict, connector_key: str) -> dict:
    return ((row.get("connectors") or {}).get(connector_key) or {}).get("body") or {}


def _target_app(row: dict, connector_key: str) -> str:
    """The app the approved step acts on, from the run's pinned connector definition."""
    return str(_connector_body(row, connector_key).get("app") or connector_key or "Your workspace")


def _operation(row: dict, connector_key: str, tool_id: str) -> str:
    """What the approved step does, named as the run timeline names it: the pinned tool's `name`, else its id
    as words."""
    tools = _connector_body(row, connector_key).get("tools") or []
    tool = next((t for t in tools if isinstance(t, dict) and t.get("id") == tool_id), None)
    return action_name(tool, tool_id)


def _step_label(row: dict, node_id: str) -> str:
    """The step as the run page names it: the node's label in the run's projection, else its id."""
    nodes = row.get("run_nodes") or []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
    return str((node or {}).get("label") or node_id)


def _unlocked(row: dict, payload: dict) -> list[UnlockedAction]:
    """The extra writes the approval's grant lets through, from the payload the worker wrote."""
    out = []
    for item in payload.get("unlocked") or []:
        tool_ref = str(item.get("tool_ref") or "")
        connector_key, _, tool_id = tool_ref.partition(".")
        out.append(
            UnlockedAction(
                app=_target_app(row, connector_key),
                step=_step_label(row, str(item.get("node") or "")),
                tool=tool_ref,
                operation=_operation(row, connector_key, tool_id),
                mocked=bool(item.get("mocked")),
                count=item.get("count"),
            )
        )
    return out


def real_approval(row: dict, names: dict[str, str] | None = None) -> Approval:
    """A run_tasks approval row as the inbox's Approval: the step it lets the run take, not an email. `names`
    (`decider_names`) says who decided it by name; an account it does not name shows as a former member."""
    payload = row["payload"] or {}
    title = str(payload.get("title") or "Approve the next step")
    summary = str(payload.get("summary") or "") or None
    tool_ref = str(payload.get("tool_ref") or "")
    connector_key, _, tool_id = tool_ref.partition(".")
    policy_ref = str(payload.get("policy_ref") or DEFAULT_POLICY_REF)
    action = ApprovalAction(
        app=_target_app(row, connector_key),
        step=_step_label(row, str(payload.get("target_node") or row["node_id"])),
        tool=tool_ref or None,
        operation=_operation(row, connector_key, tool_id) if tool_id else None,
        summary=summary,
        mocked=bool(payload.get("mocked")),
        count=payload.get("count"),
        unlocked=_unlocked(row, payload) or None,
    )
    digest = [
        DigestRow(label="Run", value=row["run_title"] or "Workflow Pack"),
        DigestRow(label="Policy", value=POLICY_LINE),
    ]
    if row["decided_by"]:
        decided_by = (names or {}).get(row["decided_by"], FORMER_MEMBER)
        digest.append(DigestRow(label="Decided by", value=decided_by))
    requested_at = iso(row["created_at"])
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        title=title,
        requested_by=row["run_title"] or "Workflow Pack",
        requested_at=requested_at,
        expires_at=str(payload.get("expires_at") or requested_at),
        status=STATUSES.get(row["status"], "PENDING"),
        policy_ref=policy_ref,
        reason_codes=["APPROVAL_REQUIRED"],
        digest=digest,
        action=action,
        summary=summary,
    )


@router.get("/approvals", operation_id="listApprovals", response_model=list[Approval])
def list_approvals(actor: CurrentActor) -> list[Approval]:
    """Approvals of real runs (newest first), then the fixtures (none in the live workspace)."""
    rows = run_tasks.list_rows(actor.org_id, "approval")
    names = decider_names(actor, rows)
    real = [real_approval(row, names) for row in rows]
    return real if workspace.live() else real + get_store().approvals


def _decide(approval_id: str, status: str) -> Approval:
    with locked_store():
        found = find_approval(approval_id)
        if found.status != "PENDING":
            raise ApiProblem(409, "CONFLICT", f"This approval is already {found.status.lower()}.")
        found.status = status
        return found


def _decide_any(approval_id: str, status: str, actor: Actor) -> Approval:
    """A real run's approval is recorded, then signalled to its workflow; otherwise the fixture is decided."""
    row = run_tasks.get_row(actor.org_id, "approval", approval_id)
    if row is None and workspace.live():
        raise ApiProblem(404, "NOT_FOUND", f"No approval {approval_id}.")
    if row is None:
        return _decide(approval_id, status)
    decision = DECISIONS[status]
    result = {"decision": decision, "by": actor.user_id, "note": ""}
    updated = run_tasks.decide(actor.org_id, "approval", approval_id, decision, actor.user_id, result)
    run_tasks.signal(
        temporal_client.signal_approval, row["run_id"], approval_id, updated["status"], updated["decided_by"]
    )
    return real_approval(updated, decider_names(actor, [updated]))


@router.post("/approvals/{approval_id}:approve", operation_id="approveApproval", response_model=Approval)
def approve_approval(approval_id: str, actor: CurrentActor) -> Approval:
    return _decide_any(approval_id, "GRANTED", actor)


@router.post("/approvals/{approval_id}:decline", operation_id="declineApproval", response_model=Approval)
def decline_approval(approval_id: str, actor: CurrentActor) -> Approval:
    return _decide_any(approval_id, "DECLINED", actor)
