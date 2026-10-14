"""The org's own reviewers and its reviewer network switch. Live workspace only: a 404 in the demo."""

from fastapi import Response

from app import org_reviewers, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.workforce import (
    AddReviewerRequest,
    OrgReviewer,
    OrgReviewers,
    RemoveReviewerRequest,
    ReviewerNetworkRequest,
)
from app.routers.org import _scope
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1", tags=["organization"])

LIVE_ONLY = "Reviewers are managed in the live workspace."


def _live_scope(org_id: str, actor: Actor) -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", LIVE_ONLY)
    _scope(org_id, actor)


@router.get("/organizations/{org_id}/reviewers", operation_id="listOrgReviewers", response_model=OrgReviewers)
def list_org_reviewers(org_id: str, actor: CurrentActor) -> OrgReviewers:
    """The org's reviewers (members with the reviewer capability, then pending Reviewer invitations) and
    whether the org allows the New Machines reviewer network."""
    _live_scope(org_id, actor)
    return org_reviewers.reviewers(org_id)


@router.post(
    "/organizations/{org_id}/reviewers",
    operation_id="addOrgReviewer",
    response_model=OrgReviewer,
    status_code=201,
)
def add_org_reviewer(org_id: str, body: AddReviewerRequest, actor: CurrentActor) -> OrgReviewer:
    """Give a member the reviewer capability, or invite anyone else as a Reviewer; they accept explicitly.
    Owners and admins only; 409 when the person already reviews for the org."""
    _live_scope(org_id, actor)
    return org_reviewers.add(org_id, actor.role, body.email)


@router.post(
    "/organizations/{org_id}/reviewers:remove",
    operation_id="removeOrgReviewer",
    status_code=204,
    response_class=Response,
)
def remove_org_reviewer(org_id: str, body: RemoveReviewerRequest, actor: CurrentActor) -> Response:
    """Remove a reviewer: a member keeps their membership without the capability, a Reviewer member leaves the
    org, a pending Reviewer invitation is withdrawn. Their claimed open tasks go back to the queue. Owners and
    admins only; 404 when the email is not a reviewer here."""
    _live_scope(org_id, actor)
    org_reviewers.remove(org_id, actor.role, body.email)
    return Response(status_code=204)


@router.put(
    "/organizations/{org_id}/reviewer-network", operation_id="setReviewerNetwork", response_model=OrgReviewers
)
def set_reviewer_network(org_id: str, body: ReviewerNetworkRequest, actor: CurrentActor) -> OrgReviewers:
    """Allow or stop the New Machines reviewer network for the org's tasks. Turning it off returns the tasks
    network reviewers claimed to the queue. Owners and admins only."""
    _live_scope(org_id, actor)
    return org_reviewers.set_network(org_id, actor.role, body.allow)
