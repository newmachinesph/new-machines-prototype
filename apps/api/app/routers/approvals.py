from app import run_tasks, temporal_client, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.work import Approval, ApprovalAction, DigestRow, UnlockedAction
from app.routing import ApiRouter
from app.store import get_store, iso, locked_store

router = ApiRouter(prefix="/v1", tags=["approvals"])

# run_tasks status of an approval -> Approval.status; the decision each endpoint sends the workflow.
STATUSES = {"pending": "PENDING", "granted": "GRANTED", "denied": "DECLINED", "timeout": "EXPIRED"}
DECISIONS = {"GRANTED": "granted", "DECLINED": "denied"}
DEFAULT_POLICY_REF = "policy/default"


def find_approval(approval_id: str) -> Approval:
    found = next((a for a in get_store().approvals if a.id == approval_id), None)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No approval {approval_id}.")
    return found


def _target_app(row: dict, connector_key: str) -> str:
    """The app the approved step acts on, from the run's pinned connector definition."""
    body = ((row.get("connectors") or {}).get(connector_key) or {}).get("body") or {}
    return str(body.get("app") or connector_key or "Your workspace")


def _unlocked(row: dict, payload: dict) -> list[UnlockedAction]:
    """The extra writes the approval's grant lets through, from the payload the worker wrote."""
    out = []
    for item in payload.get("unlocked") or []:
        tool_ref = str(item.get("tool_ref") or "")
        connector_key, _, tool_id = tool_ref.partition(".")
        out.append(
            UnlockedAction(
                app=_target_app(row, connector_key),
                step=str(item.get("node") or ""),
                tool=tool_ref,
                operation=tool_id.replace("_", " "),
                mocked=bool(item.get("mocked")),
                count=item.get("count"),
            )
        )
    return out


def real_approval(row: dict) -> Approval:
    """A run_tasks approval row as the inbox's Approval: the step it lets the run take, not an email."""
    payload = row["payload"] or {}
    title = str(payload.get("title") or "Approve the next step")
    summary = str(payload.get("summary") or "") or None
    tool_ref = str(payload.get("tool_ref") or "")
    connector_key, _, tool_id = tool_ref.partition(".")
    policy_ref = str(payload.get("policy_ref") or DEFAULT_POLICY_REF)
    action = ApprovalAction(
        app=_target_app(row, connector_key),
        step=str(payload.get("target_node") or row["node_id"]),
        tool=tool_ref or None,
        operation=tool_id.replace("_", " ") or None,
        summary=summary,
        mocked=bool(payload.get("mocked")),
        count=payload.get("count"),
        unlocked=_unlocked(row, payload) or None,
    )
    digest = [
        DigestRow(label="Run", value=row["run_id"], mono=True),
        DigestRow(label="Policy", value=f"{policy_ref} requires approval (APPROVAL_REQUIRED)"),
    ]
    if row["decided_by"]:
        digest.append(DigestRow(label="Decided by", value=row["decided_by"]))
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
    real = [real_approval(row) for row in run_tasks.list_rows(actor.org_id, "approval")]
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
    return real_approval(updated)


@router.post("/approvals/{approval_id}:approve", operation_id="approveApproval", response_model=Approval)
def approve_approval(approval_id: str, actor: CurrentActor) -> Approval:
    return _decide_any(approval_id, "GRANTED", actor)


@router.post("/approvals/{approval_id}:decline", operation_id="declineApproval", response_model=Approval)
def decline_approval(approval_id: str, actor: CurrentActor) -> Approval:
    return _decide_any(approval_id, "DECLINED", actor)
