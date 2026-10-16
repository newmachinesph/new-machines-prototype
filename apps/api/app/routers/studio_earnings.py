"""The workspace's publisher earnings (sub-project D): its share of fees, simulated. Live workspace only."""

from app import db, publisher_stats, publishers
from app.auth import CurrentActor
from app.models.publishing import PublisherEarnings
from app.routers.studio import _live
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/organizations/{org_id}/studio", tags=["studio"])


@router.get(
    "/earnings",
    operation_id="getStudioEarnings",
    response_model=PublisherEarnings,
    responses=publishers.MANAGERS_ONLY,
)
def get_studio_earnings(org_id: str, actor: CurrentActor) -> PublisherEarnings:
    """The publisher share of this month's fees and the simulated payouts of earlier months. Simulated: no
    money moves. Owners and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    publishers.require_manager(actor)
    with db.connect() as conn:
        return publisher_stats.earnings(conn, actor.org_id)
