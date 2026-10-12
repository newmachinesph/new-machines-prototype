"""Operator console: marketplace listings (the pack review state machine) and the connector catalog.
A listing's status decides what customers see (see `routers.catalog.is_listed`); a connector enabled or
disabled here adds or clears the demo tenant's connection."""

from app.auth import CurrentOps, OpsActor, OpsWriter
from app.errors import ApiProblem
from app.models.catalog import Pack, PackConnector, PackEstimate
from app.models.common import Money
from app.models.ops import (
    AddConnectorRequest,
    ConnectorDefaults,
    ConnectorEntry,
    ConnectorStatus,
    CreatePackRequest,
    HealthCheck,
    PackHistoryEntry,
    PackListing,
    PackListingDetail,
    PackStatus,
    ReasonRequest,
    SetDefaultsRequest,
    Toolkit,
)
from app.models.org import Connection
from app.routers.ops_params import PathId
from app.routing import ApiRouter
from app.store import Store, locked_store, utc_now

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

BASE_LATENCY_MS = 180
LATENCY_MS_PER_ID_CHAR = 7
MANUAL_HEALTH_CHECK = "Manual health check"


# Packs -------------------------------------------------------------------------------------------------


def find_listing(store: Store, slug: str) -> PackListing:
    listing = store.pack_listings.get(slug)
    if listing is None:
        raise ApiProblem(404, "NOT_FOUND", f"No pack listing {slug}.")
    return listing


def find_customer_pack(store: Store, slug: str) -> Pack:
    pack = next((p for p in store.packs if p.slug == slug), None)
    if pack is None:
        raise ApiProblem(500, "INTERNAL", f"Pack listing {slug} has no customer pack.")
    return pack


def pack_detail(store: Store, listing: PackListing) -> PackListingDetail:
    return PackListingDetail(
        **listing.model_dump(),
        pack=find_customer_pack(store, listing.slug).model_copy(deep=True),
        history=[h.model_copy() for h in store.pack_history[listing.slug]],
    )


def record(store: Store, actor: OpsActor, listing: PackListing, action: str, note: str) -> None:
    now = utc_now()
    listing.updated_at = now
    store.pack_history[listing.slug].append(
        PackHistoryEntry(at=now, by=actor.email, action=action, note=note)
    )


def move_pack(
    slug: str,
    body: ReasonRequest,
    actor: OpsActor,
    verb: str,
    allowed: tuple[PackStatus, ...],
    target: PackStatus,
) -> PackListingDetail:
    """One state-machine step: check the current status, change it, audit it, all under the lock."""
    with locked_store() as store:
        listing = find_listing(store, slug)
        before = listing.status
        if before not in allowed:
            raise ApiProblem(409, "INVALID_TRANSITION", f"A {before} pack cannot be moved with {verb}.")
        listing.status = target
        if verb == "submit":
            listing.submitted_at = utc_now()
        if verb == "reject":
            listing.review_notes = body.reason
        if verb == "approve":
            listing.review_notes = None
        record(store, actor, listing, verb, body.reason)
        store.audit(actor, f"pack.{verb}", "pack", slug, body.reason, f"Status {before} → {target}")
        return pack_detail(store, listing)


@router.get("/packs", operation_id="opsListPacks", response_model=list[PackListing])
def ops_list_packs(_: CurrentOps, status: PackStatus | None = None) -> list[PackListing]:
    with locked_store() as store:
        return [
            listing.model_copy()
            for listing in store.pack_listings.values()
            if status is None or listing.status == status
        ]


@router.get("/packs/{slug}", operation_id="opsGetPack", response_model=PackListingDetail)
def ops_get_pack(slug: PathId, _: CurrentOps) -> PackListingDetail:
    with locked_store() as store:
        return pack_detail(store, find_listing(store, slug))


@router.post("/packs", operation_id="opsCreatePack", response_model=PackListingDetail, status_code=201)
def ops_create_pack(body: CreatePackRequest, actor: OpsWriter) -> PackListingDetail:
    with locked_store() as store:
        if body.slug in store.pack_listings or any(p.slug == body.slug for p in store.packs):
            raise ApiProblem(409, "SLUG_TAKEN", f"A pack called {body.slug} already exists.")
        pack = Pack(
            slug=body.slug,
            name=body.name,
            version="0.1.0",
            publisher=body.publisher,
            category=body.category,
            outcome=body.outcome,
            description=body.description,
            agents=[],
            connectors=[PackConnector(app=c.app, access=c.access) for c in body.connectors],
            human_review=body.human_review,
            estimate=PackEstimate(
                ai_min=Money(amount_minor=0), ai_max=Money(amount_minor=0), human_max=Money(amount_minor=0)
            ),
            installed=False,
            certified=False,
            risk_class=body.risk_class,
            regions=["global"],
        )
        listing = PackListing(
            slug=pack.slug,
            name=pack.name,
            version=pack.version,
            publisher=pack.publisher,
            category=pack.category,
            status="draft",
            risk_class=pack.risk_class,
            certified=False,
            installs=0,
            runs30d=0,
            success_rate=0,
            price_note="Not priced yet",
            updated_at=utc_now(),
            connectors=[c.app for c in pack.connectors],
        )
        store.packs.append(pack)
        store.pack_listings[pack.slug] = listing
        store.pack_history[pack.slug] = []
        record(store, actor, listing, "create", body.reason)
        summary = f"Created draft {pack.name} v{pack.version} by {pack.publisher}"
        store.audit(actor, "pack.create", "pack", pack.slug, body.reason, summary)
        return pack_detail(store, listing)


@router.post("/packs/{slug}:submit", operation_id="opsSubmitPack", response_model=PackListingDetail)
def ops_submit_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    return move_pack(slug, body, actor, "submit", ("draft", "rejected"), "in_review")


@router.post("/packs/{slug}:approve", operation_id="opsApprovePack", response_model=PackListingDetail)
def ops_approve_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    return move_pack(slug, body, actor, "approve", ("in_review",), "published")


@router.post("/packs/{slug}:reject", operation_id="opsRejectPack", response_model=PackListingDetail)
def ops_reject_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    return move_pack(slug, body, actor, "reject", ("in_review",), "rejected")


@router.post("/packs/{slug}:deprecate", operation_id="opsDeprecatePack", response_model=PackListingDetail)
def ops_deprecate_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    return move_pack(slug, body, actor, "deprecate", ("published",), "deprecated")


@router.post("/packs/{slug}:republish", operation_id="opsRepublishPack", response_model=PackListingDetail)
def ops_republish_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    return move_pack(slug, body, actor, "republish", ("deprecated",), "published")


@router.post("/packs/{slug}:certify", operation_id="opsCertifyPack", response_model=PackListingDetail)
def ops_certify_pack(slug: PathId, body: ReasonRequest, actor: OpsWriter) -> PackListingDetail:
    with locked_store() as store:
        listing = find_listing(store, slug)
        if listing.status != "published":
            raise ApiProblem(
                409, "INVALID_TRANSITION", f"Only a published pack can be certified, not {listing.status}."
            )
        if listing.certified:
            raise ApiProblem(409, "INVALID_TRANSITION", f"{listing.name} is already certified.")
        listing.certified = True
        find_customer_pack(store, slug).certified = True
        record(store, actor, listing, "certify", body.reason)
        store.audit(actor, "pack.certify", "pack", slug, body.reason, "Certified false → true")
        return pack_detail(store, listing)


# Connectors --------------------------------------------------------------------------------------------


def find_connector(store: Store, connector_id: str) -> ConnectorEntry:
    entry = store.connector_catalog.get(connector_id)
    if entry is None:
        raise ApiProblem(404, "NOT_FOUND", f"No connector {connector_id}.")
    return entry


def expose_to_demo_tenant(store: Store, entry: ConnectorEntry) -> None:
    """An enabled or beta connector appears among the demo tenant's connections, not yet connected."""
    if any(c.app == entry.app for c in store.connections):
        return
    store.connections.append(
        Connection(
            app=entry.app,
            account="",
            status="not_connected",
            provider="Mock" if entry.provider == "Mock" else "Composio",
            oauth_scopes=list(entry.scopes),
            grants=[],
        )
    )


def disconnect_demo_tenant(store: Store, entry: ConnectorEntry) -> None:
    for conn in store.connections:
        if conn.app == entry.app:
            conn.status = "not_connected"
            conn.grants = []


def change_status(
    connector_id: PathId, body: ReasonRequest, actor: OpsActor, verb: str, target: ConnectorStatus
) -> ConnectorEntry:
    with locked_store() as store:
        entry = find_connector(store, connector_id)
        before = entry.status
        if before == target:
            raise ApiProblem(409, "NO_CHANGE", f"{entry.app} is already {before}.")
        entry.status = target
        if target == "enabled":
            expose_to_demo_tenant(store, entry)
        else:
            disconnect_demo_tenant(store, entry)
        summary = f"Status {before} → {target}"
        store.audit(actor, f"connector.{verb}", "connector", entry.id, body.reason, summary)
        return entry.model_copy(deep=True)


@router.get("/connectors", operation_id="opsListConnectors", response_model=list[ConnectorEntry])
def ops_list_connectors(_: CurrentOps) -> list[ConnectorEntry]:
    with locked_store() as store:
        return [c.model_copy(deep=True) for c in store.connector_catalog.values()]


@router.get("/connectors/available", operation_id="opsListAvailableToolkits", response_model=list[Toolkit])
def ops_list_available_toolkits(_: CurrentOps) -> list[Toolkit]:
    """Simulated Composio toolkit discovery, minus the ones already in the catalog."""
    with locked_store() as store:
        return [t.model_copy() for t in store.toolkits if t.slug not in store.connector_catalog]


@router.post("/connectors", operation_id="opsAddConnector", response_model=ConnectorEntry, status_code=201)
def ops_add_connector(body: AddConnectorRequest, actor: OpsWriter) -> ConnectorEntry:
    with locked_store() as store:
        if body.toolkit_slug in store.connector_catalog:
            raise ApiProblem(409, "ALREADY_ADDED", f"{body.toolkit_slug} is already in the catalog.")
        toolkit = next((t for t in store.toolkits if t.slug == body.toolkit_slug), None)
        if toolkit is None:
            raise ApiProblem(404, "NOT_FOUND", f"No toolkit {body.toolkit_slug}.")
        entry = ConnectorEntry(
            id=toolkit.slug,
            app=toolkit.name,
            category=toolkit.category,
            provider="Composio",
            auth_type=toolkit.auth_type,
            status=body.status,
            tenants_connected=0,
            calls_today=0,
            error_rate=0,
            last_health_check=HealthCheck(at=utc_now(), ok=True, latency_ms=0, note="Not checked yet"),
            defaults=ConnectorDefaults(read="permit", write="require_approval", delete="deny", money="deny"),
            scopes=[],
        )
        store.connector_catalog[entry.id] = entry
        expose_to_demo_tenant(store, entry)
        summary = f"Added {entry.app} as {body.status}"
        store.audit(actor, "connector.add", "connector", entry.id, body.reason, summary)
        return entry.model_copy(deep=True)


@router.post(
    "/connectors/{connector_id}:enable", operation_id="opsEnableConnector", response_model=ConnectorEntry
)
def ops_enable_connector(connector_id: PathId, body: ReasonRequest, actor: OpsWriter) -> ConnectorEntry:
    return change_status(connector_id, body, actor, "enable", "enabled")


@router.post(
    "/connectors/{connector_id}:disable", operation_id="opsDisableConnector", response_model=ConnectorEntry
)
def ops_disable_connector(connector_id: PathId, body: ReasonRequest, actor: OpsWriter) -> ConnectorEntry:
    return change_status(connector_id, body, actor, "disable", "disabled")


@router.post(
    "/connectors/{connector_id}:setDefaults",
    operation_id="opsSetConnectorDefaults",
    response_model=ConnectorEntry,
)
def ops_set_connector_defaults(
    connector_id: PathId, body: SetDefaultsRequest, actor: OpsWriter
) -> ConnectorEntry:
    with locked_store() as store:
        entry = find_connector(store, connector_id)
        before = entry.defaults
        if body.defaults.model_dump() == before.model_dump():
            raise ApiProblem(409, "NO_CHANGE", f"{entry.app} already has these defaults.")
        entry.defaults = ConnectorDefaults(**body.defaults.model_dump())
        changes = [
            f"{key} {getattr(before, key)} → {value}"
            for key, value in body.defaults.model_dump().items()
            if getattr(before, key) != value
        ]
        store.audit(actor, "connector.set_defaults", "connector", entry.id, body.reason, "; ".join(changes))
        return entry.model_copy(deep=True)


@router.post(
    "/connectors/{connector_id}:healthCheck",
    operation_id="opsHealthCheckConnector",
    response_model=ConnectorEntry,
)
def ops_health_check_connector(connector_id: PathId, actor: OpsWriter) -> ConnectorEntry:
    """Simulated and deterministic: healthy unless the connector is disabled."""
    with locked_store() as store:
        entry = find_connector(store, connector_id)
        if entry.status == "disabled":
            result = HealthCheck(at=utc_now(), ok=False, latency_ms=0, note="Connector is disabled")
        else:
            latency = BASE_LATENCY_MS + len(entry.id) * LATENCY_MS_PER_ID_CHAR
            result = HealthCheck(at=utc_now(), ok=True, latency_ms=latency)
        entry.last_health_check = result
        summary = f"Health check {'ok' if result.ok else 'failed'}, {result.latency_ms} ms"
        store.audit(actor, "connector.health_check", "connector", entry.id, MANUAL_HEALTH_CHECK, summary)
        return entry.model_copy(deep=True)
