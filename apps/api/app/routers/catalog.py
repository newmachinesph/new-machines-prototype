from app import live_catalog, real_runs, workspace
from app.auth import CurrentActor
from app.catalog import agents as agent_catalog
from app.catalog.packs import SandboxForecast, with_definition
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
    """Copies of `packs` seen through their pack definitions: `function`, `industries`, `agents` and
    `connectors` from the definition when the slug has one; no function or industries without one."""
    defs = {body.get("slug", key): body for key, body in latest_bodies("pack").items()}
    connectors = latest_bodies("connector") if any(p.slug in defs for p in packs) else {}
    sandboxed = SandboxForecast()
    aliases = _sample_aliases()
    out = []
    for pack in packs:
        body = defs.get(pack.slug)
        if body is None:
            pack = pack.model_copy(update={"function": None, "industries": []})
        else:
            pack = with_definition(pack, body, connectors, sandboxed)
        if aliases:
            agents = list(dict.fromkeys(aliases.get(a, a) for a in pack.agents))
            pack = pack.model_copy(update={"agents": agents})
        out.append(pack)
    return out


def _sample_aliases() -> dict[str, str]:
    """Demo sample agents folded into the definition agent of the same name (none in the live workspace)."""
    if workspace.live():
        return {}
    return agent_catalog.sample_aliases(get_store().agents)


@router.get("/workflow-packs", operation_id="listWorkflowPacks", response_model=list[Pack])
def list_workflow_packs(actor: CurrentActor) -> list[Pack]:
    """The marketplace. In the live workspace: every pack definition, `installed` for the caller's org."""
    if workspace.live():
        return live_catalog.list_packs(actor.org_id)
    with locked_store() as store:
        listed = [p for p in store.packs if is_listed(store, p)]
    return _classified(listed)


@router.get("/workflow-packs/{slug}", operation_id="getWorkflowPack", response_model=Pack)
def get_workflow_pack(slug: str, actor: CurrentActor) -> Pack:
    """One pack. `inputSchema` is the JSON Schema of the input a run takes: for every pack in the live
    workspace, and in the demo workspace for a pack that runs for real (the runtime is on and it has a
    definition)."""
    if workspace.live():
        return live_catalog.get_pack(actor.org_id, slug)
    with locked_store():
        pack = find_pack(slug)
    detail = _classified([pack])[0]
    schema = real_runs.real_input_schema(slug)
    return detail.model_copy(update={"input_schema": schema}) if schema else detail


@router.get("/catalog/taxonomy", operation_id="getCatalogTaxonomy", response_model=Taxonomy)
def get_catalog_taxonomy(_: CurrentActor) -> Taxonomy:
    """Functions and industries packs are classified by (the `taxonomy` definition)."""
    body = latest_bodies("taxonomy").get("default") or {}

    def entries(field: str) -> list[TaxonomyEntry]:
        return [TaxonomyEntry(id=str(e["id"]), name=str(e["name"])) for e in body.get(field) or []]

    return Taxonomy(functions=entries("functions"), industries=entries("industries"))


def _agents() -> list[Agent]:
    """The live workspace lists agent definitions only, used by pack definitions. The demo workspace adds the
    sample agents, and usage comes from the marketplace packs it lists."""
    if workspace.live():
        return agent_catalog.catalog(agent_catalog.definition_pack_uses(), samples=[])
    with locked_store() as store:
        listed = [p for p in store.packs if is_listed(store, p)]
        samples = list(store.agents)
    uses = [agent_catalog.PackUse(p.slug, p.name, p.agents) for p in _classified(listed)]
    return agent_catalog.catalog(uses, samples, _sample_aliases())


@router.get("/agents", operation_id="listAgents", response_model=list[Agent])
def list_agents(_: CurrentActor) -> list[Agent]:
    """Agents in the catalog: definition agents first, then (demo workspace only) sample agents."""
    return _agents()


@router.get("/agents/{agent_id}", operation_id="getAgent", response_model=Agent)
def get_agent(agent_id: str, _: CurrentActor) -> Agent:
    # In the demo workspace a folded sample id (agent_finance) returns its definition agent.
    agent_id = _sample_aliases().get(agent_id, agent_id)
    agent = next((a for a in _agents() if a.id == agent_id), None)
    if agent is None:
        raise ApiProblem(404, "NOT_FOUND", f"No agent called {agent_id}.")
    return agent


@router.post("/workflow-packs:suggest", operation_id="suggestWorkflowPack", response_model=Suggestion)
def suggest_workflow_pack(body: SuggestRequest, actor: CurrentActor) -> Suggestion:
    """Keyword match for the static API. The dynamic backend asks Gemini and keeps this response shape.
    The live workspace matches over the pack definitions."""
    if workspace.live():
        return live_catalog.suggest(actor.org_id, body.text)
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
    if workspace.live():
        return live_catalog.install(actor, body)
    with locked_store():
        pack = find_pack(body.pack_slug)
        pack.installed = True
    reviewers = "your team and the New Machines reviewer pool" if body.reviewer_pool else "your team only"
    summary = f"Spending cap ${body.cap_minor / 100:.2f} per run. Reviewers: {reviewers}."
    return Installation(
        pack_slug=pack.slug, cap_minor=body.cap_minor, reviewer_pool=body.reviewer_pool, summary=summary
    )
