from typing import Annotated

from fastapi import Path

from app import workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.org import Me
from app.routing import ApiRouter
from app.store import get_store

router = ApiRouter(prefix="/v1", tags=["organization"])

OrgId = Annotated[str, Path(description="The org that sent the invitation.")]


def _identity(actor: Actor) -> workspace.Identity:
    return workspace.Identity(
        user_id=actor.user_id, email=actor.email, email_verified=actor.email_verified, name=actor.name
    )


def _me(actor: Actor) -> Me:
    live = workspace.live()
    return Me(
        user_id=actor.user_id,
        email=actor.email,
        name=actor.name,
        org_id=actor.org_id,
        org_name=actor.org_name or get_store().org.name,
        role=actor.role,
        workspace="live" if live else "demo",
        invitations=workspace.pending_invitations(_identity(actor), actor.org_id) if live else [],
    )


def _live_only() -> None:
    """The demo workspace has no invitations to answer: these routes are a 404 there."""
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", "There is no pending invitation to this workspace.")


@router.get("/me", operation_id="getMe", response_model=Me)
def get_me(actor: CurrentActor) -> Me:
    """The signed-in user and their workspace: their own org in the live workspace, the seeded org in the
    demo. `invitations` lists pending invitations to other workspaces for the user's verified email (live
    workspace only)."""
    return _me(actor)


@router.post("/invitations/{org_id}:accept", operation_id="acceptInvitation", response_model=Me)
def accept_invitation(org_id: OrgId, actor: CurrentActor) -> Me:
    """Join the workspace that invited the user's verified email; the user leaves their current one (an
    empty workspace is deleted, any other keeps its data). 403 when the email is not verified, 404 when there
    is no such pending invitation, and always 404 in the demo workspace."""
    _live_only()
    member = workspace.accept_invitation(_identity(actor), org_id)
    joined = Actor(
        user_id=actor.user_id,
        org_id=member.org_id,
        role=member.role,
        email=actor.email,
        name=actor.name,
        org_name=member.org_name,
        email_verified=actor.email_verified,
    )
    return _me(joined)


@router.post("/invitations/{org_id}:decline", operation_id="declineInvitation", response_model=Me)
def decline_invitation(org_id: OrgId, actor: CurrentActor) -> Me:
    """Decline a pending invitation for the user's verified email; it is deleted. 403 when the email is not
    verified, 404 when there is no such invitation, and always 404 in the demo workspace."""
    _live_only()
    workspace.decline_invitation(_identity(actor), org_id)
    return _me(actor)
