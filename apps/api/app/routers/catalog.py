from app.auth import CurrentActor
from app.errors import ApiProblem
from app.models.catalog import Agent, Pack, Suggestion
from app.models.requests import Installation, InstallRequest, SuggestRequest
from app.routers.org import require_org
from app.routing import ApiRouter
from app.store import get_store, locked_store

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


def find_pack(slug: str) -> Pack:
    pack = next((p for p in get_store().packs if p.slug == slug), None)
    if pack is None:
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    return pack


@router.get("/workflow-packs", operation_id="listWorkflowPacks", response_model=list[Pack])
def list_workflow_packs(_: CurrentActor) -> list[Pack]:
    return get_store().packs


@router.get("/workflow-packs/{slug}", operation_id="getWorkflowPack", response_model=Pack)
def get_workflow_pack(slug: str, _: CurrentActor) -> Pack:
    return find_pack(slug)


@router.get("/agents", operation_id="listAgents", response_model=list[Agent])
def list_agents(_: CurrentActor) -> list[Agent]:
    return get_store().agents


@router.post("/workflow-packs:suggest", operation_id="suggestWorkflowPack", response_model=Suggestion)
def suggest_workflow_pack(body: SuggestRequest, _: CurrentActor) -> Suggestion:
    """Keyword match for the static API. The dynamic backend asks Gemini and keeps this response shape."""
    words = set(body.text.lower().replace(",", " ").split())
    best = max(WORDS, key=lambda slug: len(WORDS[slug] & words))
    if not WORDS[best] & words:
        return Suggestion(
            steps=["Describe the result you want, the apps involved and how often."], simulated=True
        )
    pack = find_pack(best)
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
