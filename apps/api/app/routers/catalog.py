from app.auth import CurrentActor
from app.defs.current import latest_bodies
from app.errors import ApiProblem
from app.models.catalog import Agent, Pack, Suggestion, Taxonomy, TaxonomyEntry
from app.models.requests import Installation, InstallRequest, SuggestRequest
from app.routers.org import require_org
from app.routing import ApiRouter
from app.store import Store, get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["catalog"])

WORDS = {
    "order-payment-reconciliation": {"reconcile", "payout", "payouts", "stripe", "orders", "match"},
    "overdue-invoice-follow-up": {"invoice", "invoices", "overdue", "chase", "wholesale", "reminder"},
    "refund-triage": {"refund", "refunds", "support", "return", "returns"},
    "weekly-inventory-report": {"inventory", "reorder", "stock", "sku", "skus", "monday"},
    "shipping-exceptions": {"shipping", "parcel", "parcels", "carrier", "late", "lost"},
    "chargeback-evidence": {"chargeback", "chargebacks", "dispute", "disputes"},
    "catalog-localization-en-ja": {"translate", "japanese", "catalog", "localize", "localization"},
}


def is_listed(store: Store, pack: Pack) -> bool:
    """The marketplace effect of the ops listing: published packs are shown, a deprecated one only while the
    demo tenant has it installed. A pack without a listing is treated as published."""
    listing = store.pack_listings.get(pack.slug)
    if listing is None or listing.status == "published":
        return True
    return listing.status == "deprecated" and pack.installed


def find_pack(slug: str) -> Pack:
    store = get_store()
    pack = next((p for p in store.packs if p.slug == slug and is_listed(store, p)), None)
    if pack is None:
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    return pack


def _classified(packs: list[Pack]) -> list[Pack]:
    """Copies of `packs` with `function` and `industries` from their pack definitions (none without one)."""
    defs = {body.get("slug", key): body for key, body in latest_bodies("pack").items()}
    out = []
    for pack in packs:
        body = defs.get(pack.slug) or {}
        industries = [str(i) for i in body.get("industries") or []]
        out.append(pack.model_copy(update={"function": body.get("function"), "industries": industries}))
    return out


@router.get("/workflow-packs", operation_id="listWorkflowPacks", response_model=list[Pack])
def list_workflow_packs(_: CurrentActor) -> list[Pack]:
    with locked_store() as store:
        listed = [p for p in store.packs if is_listed(store, p)]
    return _classified(listed)


@router.get("/workflow-packs/{slug}", operation_id="getWorkflowPack", response_model=Pack)
def get_workflow_pack(slug: str, _: CurrentActor) -> Pack:
    with locked_store():
        pack = find_pack(slug)
    return _classified([pack])[0]


@router.get("/catalog/taxonomy", operation_id="getCatalogTaxonomy", response_model=Taxonomy)
def get_catalog_taxonomy(_: CurrentActor) -> Taxonomy:
    """Functions and industries packs are classified by (the `taxonomy` definition)."""
    body = latest_bodies("taxonomy").get("default") or {}

    def entries(field: str) -> list[TaxonomyEntry]:
        return [TaxonomyEntry(id=str(e["id"]), name=str(e["name"])) for e in body.get(field) or []]

    return Taxonomy(functions=entries("functions"), industries=entries("industries"))


@router.get("/agents", operation_id="listAgents", response_model=list[Agent])
def list_agents(_: CurrentActor) -> list[Agent]:
    return get_store().agents


@router.post("/workflow-packs:suggest", operation_id="suggestWorkflowPack", response_model=Suggestion)
def suggest_workflow_pack(body: SuggestRequest, _: CurrentActor) -> Suggestion:
    """Keyword match for the static API. The dynamic backend asks Gemini and keeps this response shape."""
    words = set(body.text.lower().replace(",", " ").split())
    with locked_store() as store:
        listed = [p.slug for p in store.packs if p.slug in WORDS and is_listed(store, p)]
        best = max(listed, key=lambda slug: len(WORDS[slug] & words), default=None)
        if best is None or not WORDS[best] & words:
            return Suggestion(
                steps=["Describe the result you want, the apps involved and how often."], simulated=True
            )
        pack = find_pack(best)
    pack = _classified([pack])[0]
    steps = [
        f"Read the data it needs from {', '.join(c.app for c in pack.connectors)}.",
        f"{pack.outcome}",
        f"A person steps in when needed: {pack.human_review.lower()}",
        "An independent check verifies the result before you accept it.",
    ]
    return Suggestion(pack=pack, steps=steps, simulated=True)


@router.post(
    "/organizations/{org_id}/agent-installations",
    operation_id="installWorkflowPack",
    response_model=Installation,
    status_code=201,
)
def install_workflow_pack(org_id: str, body: InstallRequest, actor: CurrentActor) -> Installation:
    require_org(org_id, actor)
    with locked_store():
        pack = find_pack(body.pack_slug)
        pack.installed = True
    reviewers = "your team and the New Machines reviewer pool" if body.reviewer_pool else "your team only"
    summary = f"Spending cap ${body.cap_minor / 100:.2f} per run. Reviewers: {reviewers}."
    return Installation(
        pack_slug=pack.slug, cap_minor=body.cap_minor, reviewer_pool=body.reviewer_pool, summary=summary
    )
