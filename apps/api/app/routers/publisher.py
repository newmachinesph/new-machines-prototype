"""The workspace's publisher profile (sub-project D): the name its listings show in other workspaces'
marketplaces, a short description and simulated payout details. Live workspace only (404 in the demo)."""

from app import publishers, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.publishing import PublisherRequest, PublisherSettings
from app.routers.org import _scope
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/organizations/{org_id}/publisher", tags=["publishing"])

LIVE_ONLY = "Publishing is part of the live workspace."


def _live(org_id: str, actor: Actor) -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", LIVE_ONLY)
    _scope(org_id, actor)


@router.get(
    "", operation_id="getPublisher", response_model=PublisherSettings, responses=publishers.MANAGERS_ONLY
)
def get_publisher(org_id: str, actor: CurrentActor) -> PublisherSettings:
    """The workspace's publisher profile. `enabled` is false until an owner or admin turns publishing on.
    Payout details are simulated: no money moves. Owners and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    publishers.require_manager(actor)
    return publishers.settings(actor.org_id)


@router.put(
    "", operation_id="savePublisher", response_model=PublisherSettings, responses=publishers.MANAGERS_ONLY
)
def save_publisher(org_id: str, body: PublisherRequest, actor: CurrentActor) -> PublisherSettings:
    """Turn publishing on, or update the profile. Owners and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    return publishers.save(actor, body)


@router.delete(
    "", operation_id="disablePublisher", response_model=PublisherSettings, responses=publishers.MANAGERS_ONLY
)
def disable_publisher(org_id: str, actor: CurrentActor) -> PublisherSettings:
    """Turn publishing off: no new submissions. Listings stay as they are; New Machines unlists them. Owners
    and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    return publishers.disable(actor)
