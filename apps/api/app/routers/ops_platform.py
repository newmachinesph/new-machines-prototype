"""Operator console: who is signed in, the operator team and the audit log."""

from typing import Annotated

from fastapi import Query

from app import db, ops_state, workspace
from app.auth import CurrentOps
from app.models.ops import AuditEntry, AuditTargetType, OpsMe, OpsTeamMember
from app.routing import ApiRouter
from app.store import locked_store

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

AUDIT_DEFAULT_LIMIT = 100
AUDIT_MAX_LIMIT = 500


@router.get("/me", operation_id="opsGetMe", response_model=OpsMe)
def ops_get_me(actor: CurrentOps) -> OpsMe:
    return OpsMe(
        user_id=actor.user_id,
        email=actor.email,
        role=actor.role,
        workspace="live" if workspace.live() else "demo",
    )


@router.get("/team", operation_id="opsListTeam", response_model=list[OpsTeamMember])
def ops_list_team(_: CurrentOps) -> list[OpsTeamMember]:
    with locked_store() as store:
        return [member.model_copy() for member in store.ops_team]


def _live_audit(target_type: str | None, target_id: str | None, limit: int) -> list[AuditEntry]:
    with db.connect() as conn:
        rows = ops_state.list_audit(conn, limit, target_type=target_type, target_id=target_id)
    return [ops_state.audit_entry(r) for r in rows]


@router.get("/audit", operation_id="opsListAudit", response_model=list[AuditEntry])
def ops_list_audit(
    _: CurrentOps,
    target_type: Annotated[AuditTargetType | None, Query(alias="targetType")] = None,
    target_id: Annotated[str | None, Query(alias="targetId", max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=AUDIT_MAX_LIMIT)] = AUDIT_DEFAULT_LIMIT,
) -> list[AuditEntry]:
    """Newest first. Entries with the same timestamp keep the order they were written in, newest first.
    The live workspace reads the persisted ops audit log."""
    if workspace.live():
        return _live_audit(target_type, target_id, limit)
    with locked_store() as store:
        entries = [
            e
            for e in reversed(store.audit_log)
            if (target_type is None or e.target_type == target_type)
            and (target_id is None or e.target_id == target_id)
        ]
    return sorted(entries, key=lambda e: e.at, reverse=True)[:limit]
