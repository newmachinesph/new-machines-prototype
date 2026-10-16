"""Submitting the workspace's own agents and packs for the marketplace, and its listings with their review
history (sub-project D). Live workspace only; every route is scoped to the caller's org."""

from typing import Annotated

from fastapi import Path

from app import db, listing_checks, listings, publisher_stats, publishers
from app.auth import CurrentActor
from app.errors import TITLES, ApiProblem, Problem, conflicts
from app.models.common import Money
from app.models.publishing import LISTING_ID_PATTERN, StudioListing, StudioListingDetail, SubmitListingRequest
from app.routers.runs import UNAVAILABLE, _check_live_not_paused
from app.routers.studio import StudioKey, _live
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/organizations/{org_id}/studio", tags=["studio"])

ListingId = Annotated[str, Path(pattern=LISTING_ID_PATTERN)]
SUBMIT_CONFLICTS = (
    "PUBLISHER_PROFILE_REQUIRED",
    "SUBMISSION_OPEN",
    "PLATFORM_PAUSED",
    "SANDBOX_UNAVAILABLE",
    "SPEND_CAP",
    "PACK_UNAVAILABLE",
    "NOT_PUBLISHABLE",
    "VERSION_CONFLICT",
)


def _listing(conn, row: dict, numbers: dict, detail: bool = False) -> StudioListing:
    versions = listings.versions(conn, row["id"])
    current = next((v for v in versions if v.id == row["current_version_id"]), None)
    n = numbers.get(row["id"]) or publisher_stats.ListingNumbers(0, 0, 0)
    fields = dict(
        id=row["id"],
        kind=row["kind"],
        key=row["definition_key"],
        name=row["name"],
        status=row["status"],
        price=Money(amount_minor=int(row["price_minor"])),
        latest=versions[0],
        approved_version=current.definition_version if current else None,
        installs=n.installs,
        runs30d=n.runs30d,
        earnings_month=Money(amount_minor=n.earnings_month_minor),
    )
    return StudioListingDetail(**fields, versions=versions) if detail else StudioListing(**fields)


def _detail(org_id: str, listing_id: str) -> StudioListingDetail:
    with db.connect() as conn:
        listings.settle_checks(conn, org_id)
        conn.commit()  # settle_checks locks listings: release them before anything else
        row = listings.get(conn, listing_id)
        # Another workspace's listing does not exist here.
        if row is None or row["publisher_org_id"] != org_id:
            raise ApiProblem(404, "NOT_FOUND", f"No listing {listing_id}.")
        return _listing(conn, row, publisher_stats.listing_numbers(conn, org_id), detail=True)


@router.post(
    "/agents/{key}/submissions",
    operation_id="submitStudioAgent",
    response_model=StudioListingDetail,
    status_code=201,
    responses={
        **conflicts(*SUBMIT_CONFLICTS),
        422: {"model": Problem, "description": f"{TITLES[422]} (INVALID_DEFINITION, INVALID_INPUT)."},
        503: {"model": Problem, "description": UNAVAILABLE},
    },
)
def submit_studio_agent(
    org_id: str, key: StudioKey, body: SubmitListingRequest, actor: CurrentActor
) -> StudioListingDetail:
    """Submit the agent's saved version for the marketplace at a per-call price. Owners and admins of a
    workspace with a publisher profile. The automatic checks run first: the definition checks (422 with each
    problem; nothing is recorded) and a sandbox call of the agent through the agent runtime. The version waits
    in `checking` until that run ends, then in `in_review` for New Machines."""
    _live(org_id, actor)
    _check_live_not_paused()
    return _detail(actor.org_id, listing_checks.submit(actor, "agent", key, body))


@router.post(
    "/packs/{key}/submissions",
    operation_id="submitStudioPack",
    response_model=StudioListingDetail,
    status_code=201,
    responses={
        **conflicts(*SUBMIT_CONFLICTS),
        422: {
            "model": Problem,
            "description": f"{TITLES[422]} (INVALID_DEFINITION, PRIVATE_AGENTS, INVALID_INPUT, "
            "BUDGET_REQUIRED, BUDGET_TOO_HIGH).",
        },
        503: {"model": Problem, "description": UNAVAILABLE},
    },
)
def submit_studio_pack(
    org_id: str, key: StudioKey, body: SubmitListingRequest, actor: CurrentActor
) -> StudioListingDetail:
    """Submit the pack's saved version for the marketplace at a per-run price. Owners and admins of a
    workspace with a publisher profile. Every agent in the pack must be the platform's or listed (422
    PRIVATE_AGENTS names the agents that need to be listed first, each with where it stands: not submitted,
    in review, unlisted or not approved). A pack that uses the org's own MCP server cannot be submitted (409
    NOT_PUBLISHABLE). The automatic checks run the definition checks and a
    sandbox test run with `input` and `budgetMinor` (a completed sandbox test of this version is reused). The
    version waits in `checking` until that run ends, then in `in_review` for New Machines."""
    _live(org_id, actor)
    _check_live_not_paused()
    return _detail(actor.org_id, listing_checks.submit(actor, "pack", key, body))


@router.get(
    "/listings",
    operation_id="listStudioListings",
    response_model=list[StudioListing],
    responses=publishers.MANAGERS_ONLY,
)
def list_studio_listings(org_id: str, actor: CurrentActor) -> list[StudioListing]:
    """The workspace's listings: status, the newest submission, installs, runs in the last 30 days and this
    month's earnings (simulated). Owners and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    publishers.require_manager(actor)
    with db.connect() as conn:
        listings.settle_checks(conn, actor.org_id)
        conn.commit()  # settle_checks locks listings: release them before anything else
        numbers = publisher_stats.listing_numbers(conn, actor.org_id)
        return [_listing(conn, r, numbers) for r in listings.for_publisher(conn, actor.org_id)]


@router.get(
    "/listings/{listing_id}",
    operation_id="getStudioListing",
    response_model=StudioListingDetail,
    responses=publishers.MANAGERS_ONLY,
)
def get_studio_listing(org_id: str, listing_id: ListingId, actor: CurrentActor) -> StudioListingDetail:
    """One of the workspace's listings with every submitted version, its checks and the review notes. Owners
    and admins only (403 POLICY_DENIED)."""
    _live(org_id, actor)
    publishers.require_manager(actor)
    return _detail(actor.org_id, listing_id)
