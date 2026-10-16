"""Developer publishing (sub-project D): the publisher profile, listings and their review, and publisher fees.
Money here is simulated: payouts, earnings and payout details never move money."""

from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from app.models.common import Model, Money, Opt, RequestModel

ListingKind = Literal["agent", "pack"]
ListingStatus = Literal["pending", "listed", "unlisted"]
VersionStatus = Literal["checking", "checks_failed", "in_review", "approved", "changes_requested", "rejected"]
OpsListingFilter = Literal["in_review", "pending", "listed", "unlisted"]
CheckName = Literal["definition", "agents", "sandbox"]
CheckState = Literal["passed", "failed", "running"]
FeeKind = Literal["pack_run", "agent_call"]
FeeUnit = Literal["run", "call"]

LISTING_ID_PATTERN = r"^lst_[0-9a-f]{12}$"
MAX_PRICE_MINOR = 100_000  # $1,000.00 per run or per call

PublisherName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)]


class PublisherRequest(RequestModel):
    """Turn publishing on, or change the profile. `payout_note` is simulated payout details."""

    name: PublisherName
    description: ShortNote = ""
    payout_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""


class PublisherProfile(Model):
    name: str
    description: str
    payout_note: str
    updated_at: str


class PublisherSettings(Model):
    """`enabled` is whether the workspace may submit; `profile` is absent until publishing is first turned on
    and kept when it is turned off. Payout details and payouts are simulated: no money moves."""

    enabled: bool
    profile: PublisherProfile | Opt = None
    simulated: bool = True


class SubmitListingRequest(RequestModel):
    """The price (per run for a pack, per call for an agent; 0 is "No fee") and, for a pack, the input and
    budget of the sandbox test run the automatic checks start."""

    price_minor: int = Field(ge=0, le=MAX_PRICE_MINOR)
    input: dict[str, Any] = Field(default_factory=dict)
    budget_minor: int | Opt = Field(default=None, gt=0, le=100_000)


class ListingCheck(Model):
    name: CheckName
    state: CheckState
    detail: str
    run_id: str | Opt = None  # the sandbox run, for "sandbox"


class ListingVersion(Model):
    id: str
    definition_version: int
    status: VersionStatus
    price: Money
    checks: list[ListingCheck]
    submitted_at: str
    submitted_by: str
    decided_at: str | Opt = None
    decided_by: str | Opt = None
    note: str | Opt = None  # ops' note (changes requested, rejected, approved)


class StudioListing(Model):
    """One of the workspace's listings on its Publisher tab. Earnings are simulated."""

    id: str
    kind: ListingKind
    key: str
    name: str
    status: ListingStatus
    price: Money
    latest: ListingVersion
    approved_version: int | Opt = None
    installs: int
    runs30d: int = Field(alias="runs30d")
    earnings_month: Money
    simulated: bool = True


class StudioListingDetail(StudioListing):
    versions: list[ListingVersion]  # newest first


class PayoutMonth(Model):
    month: str  # "2026-09"
    amount: Money
    status: Literal["SIMULATED"] = "SIMULATED"


class PublisherEarnings(Model):
    """The publisher share of fees: this calendar month (UTC) and the simulated payouts of earlier months."""

    month: Money
    payouts: list[PayoutMonth]  # newest first, at most 12
    simulated: bool = True


class FeeItem(Model):
    """One listing's publisher fees in a run: the quantity charged at the unit price, and the amount."""

    listing_id: str
    name: str
    publisher: str
    kind: FeeKind
    quantity: int
    unit: Money
    amount: Money


class MarketplaceListing(Model):
    """Another workspace's listed agent or pack. `fee` is per run (pack) or per call (agent); 0 shows as
    "No fee". `version` is the newest approved version; `installed_version` and `update_available` are set on
    a pack the workspace has added."""

    listing_id: str
    publisher: str
    fee: Money
    fee_unit: FeeUnit
    version: int
    installed_version: int | Opt = None
    update_available: bool | Opt = None


class DefinitionDiff(Model):
    kind: str
    key: str
    path: str
    change: Literal["added", "changed", "removed"]
    unified: str


class OpsListing(Model):
    id: str
    kind: ListingKind
    key: str
    name: str
    publisher: str
    publisher_org_id: str
    status: ListingStatus
    price: Money
    updated_at: str
    pending: ListingVersion | Opt = None  # the version checking or waiting for review


class ListingHistoryEntry(Model):
    """One ops action on a listing, from `ops_audit`."""

    at: str
    by: str
    action: str  # listing.approve, listing.request-changes, listing.reject, listing.unlist, listing.relist
    note: str


class OpsListingDetail(OpsListing):
    versions: list[ListingVersion]  # newest first
    diff: list[DefinitionDiff]  # the newest version against the current approved one
    history: list[ListingHistoryEntry]  # newest first
