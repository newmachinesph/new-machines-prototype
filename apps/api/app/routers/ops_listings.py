"""Operator console: the review queue for listed agents and packs (sub-project D). Admins and owners decide;
support reads. Every decision, unlist and relist is audited. Live workspace only (404 in the demo, whose pack
review stays on /v1/ops/packs)."""

from typing import Annotated

from fastapi import Path

from app import db, listing_diff, listings, ops_state, workspace
from app.auth import CurrentOps, OpsWriter
from app.errors import ApiProblem, conflicts
from app.models.common import Money
from app.models.ops import ReasonRequest
from app.models.publishing import (
    LISTING_ID_PATTERN,
    ListingHistoryEntry,
    OpsListing,
    OpsListingDetail,
    OpsListingFilter,
)
from app.routing import ApiRouter
from app.store import iso

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

ListingId = Annotated[str, Path(pattern=LISTING_ID_PATTERN)]
LIVE_ONLY = "Listings are part of the live workspace."


def _live() -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", LIVE_ONLY)


def _not_found(listing_id: str) -> ApiProblem:
    return ApiProblem(404, "NOT_FOUND", f"No listing {listing_id}.")


def _ops_listing(conn, row: dict) -> OpsListing:
    return OpsListing(
        id=row["id"],
        kind=row["kind"],
        key=row["definition_key"],
        name=row["name"],
        publisher=row["publisher"],
        publisher_org_id=row["publisher_org_id"],
        status=row["status"],
        price=Money(amount_minor=int(row["price_minor"])),
        updated_at=iso(row["updated_at"]),
        pending=listings.open_version(conn, row["id"]),
    )


def _detail(conn, listing_id: str) -> OpsListingDetail:
    row = listings.get(conn, listing_id)
    if row is None:
        raise _not_found(listing_id)
    bundles = {
        r["id"]: r["definitions"]
        for r in conn.execute(
            "SELECT id, definitions FROM listing_versions WHERE listing_id = %s", (listing_id,)
        )
    }
    versions = listings.versions(conn, listing_id)
    newest = versions[0] if versions else None
    current = row["current_version_id"]
    changes = (
        listing_diff.diff(conn, bundles.get(current), bundles[newest.id])
        if newest and newest.id != current
        else []
    )
    history = [
        ListingHistoryEntry(at=iso(a["at"]), by=a["actor_email"], action=a["action"], note=a["reason"])
        for a in ops_state.list_audit(conn, 100, target_type="listing", target_id=listing_id)
    ]
    return OpsListingDetail(
        **_ops_listing(conn, row).model_dump(), versions=versions, diff=changes, history=history
    )


@router.get("/listings", operation_id="opsListListings", response_model=list[OpsListing])
def ops_list_listings(_: CurrentOps, status: OpsListingFilter | None = None) -> list[OpsListing]:
    """Every workspace's listings, newest change first. `status=in_review` is the review queue (a version
    waits for a decision); `pending`, `listed` and `unlisted` filter on the listing."""
    _live()
    with db.connect() as conn:
        listings.settle_checks(conn)
        conn.commit()
        return [_ops_listing(conn, r) for r in listings.for_ops(conn, status)]


@router.get("/listings/{listing_id}", operation_id="opsGetListing", response_model=OpsListingDetail)
def ops_get_listing(listing_id: ListingId, _: CurrentOps) -> OpsListingDetail:
    """One listing: its versions with check results and sandbox run, the newest version's diff against the
    approved one, the price and the ops history."""
    _live()
    with db.connect() as conn:
        listings.settle_checks(conn)
        conn.commit()
        return _detail(conn, listing_id)


def _decision(verb: str, doc: str, operation_id: str):
    @router.post(
        f"/listings/{{listing_id}}:{verb}",
        operation_id=operation_id,
        response_model=OpsListingDetail,
        responses=conflicts("INVALID_TRANSITION"),
        description=doc,
    )
    def decide(listing_id: ListingId, body: ReasonRequest, actor: OpsWriter) -> OpsListingDetail:
        _live()
        with db.connect() as conn:
            listings.settle_checks(conn)
            conn.commit()  # settle_checks locks listings: release them before the decision takes its own
            try:
                if verb in listings.DECISIONS:
                    listings.decide(conn, listing_id, verb, actor.email, body.reason, actor_role=actor.role)
                else:
                    listings.move(conn, listing_id, verb, actor.email, body.reason, actor_role=actor.role)
            except LookupError:
                raise _not_found(listing_id) from None
            except listings.Transition as exc:
                raise ApiProblem(409, "INVALID_TRANSITION", str(exc)) from None
            conn.commit()
            return _detail(conn, listing_id)

    decide.__name__ = f"ops_{verb.replace('-', '_')}_listing"
    return decide


_decision(
    "approve",
    "Approve the version in review: it becomes the listed version. The reason is the note "
    "the publisher sees.",
    "opsApproveListing",
)
_decision(
    "request-changes",
    "Send the version in review back to the publisher with a note of what to change.",
    "opsRequestListingChanges",
)
_decision("reject", "Reject the version in review, with a note the publisher sees.", "opsRejectListing")
_decision(
    "unlist",
    "Take a listed agent or pack out of every other workspace's marketplace and Studio; new runs of it stop.",
    "opsUnlistListing",
)
_decision("relist", "List an unlisted agent or pack again at its approved version.", "opsRelistListing")
