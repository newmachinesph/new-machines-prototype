"""The live workspace marketplace: every pack definition is a Workflow Pack, hired per org in the
`installations` table. Reads the latest definitions from the Postgres registry (the live workspace always has
the runtime on) and never the demo fixtures. Every installation query is scoped to one org."""

import re
from dataclasses import dataclass, field, replace

from app import db, fees, listing_pins, listings, live_connections, run_tasks, workspace
from app.auth import Actor
from app.catalog.agents import market_listing
from app.catalog.packs import SandboxForecast, pack_connectors
from app.defs import owners, registry
from app.errors import ApiProblem
from app.models.catalog import Pack, PackEstimate, Suggestion
from app.models.common import Money
from app.models.ops import PackListing
from app.models.requests import Installation, InstallRequest
from app.runtime.projection import TERMINAL_RUN_STATUSES
from app.store import locked_store

# How each reviewer pool reads in a hire's summary.
POOL_WORDS: dict[str, str] = {
    "team": "your team only",
    "network": "the New Machines reviewer network",
    "team_then_network": "your team first, then the New Machines reviewer network after 30 minutes",
}


# A pool that names the network while the org's switch is off: its tasks stay with the team.
TEAM_FOR_NOW = (
    "your team only for now. The reviewer network is off for your workspace, so your team reviews every task "
    "until an owner or admin allows the network on Reviewers"
)


def hire_summary(cap_minor: int, pool: str, network_on: bool = True) -> str:
    """The hire's cap and reviewers. With the org's network switch off (live workspace), a pool that names the
    network does not claim network routing that cannot happen."""
    words = POOL_WORDS[pool] if network_on or pool == "team" else TEAM_FOR_NOW
    return f"Spending cap ${cap_minor / 100:.2f} per run. Reviewers: {words}."


_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "our",
        "your",
        "their",
        "every",
        "each",
        "when",
        "what",
        "how",
        "who",
        "all",
        "any",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "not",
        "but",
        "can",
        "will",
        "would",
        "should",
        "could",
        "about",
        "after",
        "before",
        "then",
        "than",
        "them",
        "they",
    }
)


@dataclass(frozen=True)
class Definitions:
    """The version of every definition one org may see, by kind and key: the latest of the platform's and the
    org's own, the approved one of what other workspaces list. `team` holds the (kind, key) of the org's own
    definitions."""

    by_kind: dict[str, dict[str, registry.Version]]
    team: frozenset[tuple[str, str]] = frozenset()
    # Another workspace's listed packs and agents, by (kind, key), at their approved version (sub-project D).
    # Empty without an org; never the org's own listings.
    listed: dict[tuple[str, str], listings.MarketRow] = field(default_factory=dict)

    def bodies(self, kind: str) -> dict[str, dict]:
        return {key: v.body for key, v in self.by_kind.get(kind, {}).items()}

    def pack(self, slug: str) -> registry.Version | None:
        """The pack definition whose slug (or key) is `slug`."""
        packs = self.by_kind.get("pack", {})
        found = next((v for v in packs.values() if v.body.get("slug") == slug), None)
        return found or packs.get(slug)

    def packs(self) -> list[registry.Version]:
        return [v for _, v in sorted(self.by_kind.get("pack", {}).items())]

    def is_team(self, kind: str, key: str) -> bool:
        return (kind, key) in self.team


def definitions(org_id: str | None = None) -> Definitions:
    """What `org_id` may see: the platform's definitions, the org's own and what other workspaces list (None:
    the platform's only)."""
    with db.connect() as conn:
        versions = registry.latest_visible(conn, org_id)
        team = registry.team_keys(conn, org_id) if org_id else set()
        listed = listings.market_info(conn, org_id) if org_id else {}
    by_kind: dict[str, dict[str, registry.Version]] = {}
    for v in versions:
        by_kind.setdefault(v.kind, {})[v.key] = v
    return Definitions(by_kind, frozenset(team), listed)


def slug_of(version: registry.Version) -> str:
    return str(version.body.get("slug") or version.key)


def contract_of(defs: Definitions, pack: dict) -> dict:
    """The pack's Work Contract body: its workflow's `work_contract_ref`, else the pack's `contract`."""
    workflow = defs.bodies("workflow").get(str(pack.get("workflow") or "")) or {}
    key = workflow.get("work_contract_ref") or pack.get("contract") or ""
    return defs.bodies("contract").get(str(key)) or {}


def input_schema(defs: Definitions, pack: dict) -> dict | None:
    """The JSON Schema of the input a run of this pack takes (its contract's `input_schema_ref`)."""
    ref = contract_of(defs, pack).get("input_schema_ref")
    return defs.bodies("schema").get(str(ref)) if ref else None


def _estimate(contract: dict) -> PackEstimate:
    """The contract budget: at most `maximum_minor` a run, `human_budget_minor` of it for reviewers."""
    budget = contract.get("budget") or {}
    maximum = int(budget.get("maximum_minor") or 0)
    human = int(budget.get("human_budget_minor") or 0)
    return PackEstimate(
        ai_min=Money(amount_minor=0),
        ai_max=Money(amount_minor=max(maximum - human, 0)),
        human_max=Money(amount_minor=human),
    )


def max_budget(contract: dict) -> Money | None:
    """The most a run may be given (`budget.maximum_minor`, as the start checks it); None without one."""
    maximum = int((contract.get("budget") or {}).get("maximum_minor") or 0)
    return Money(amount_minor=maximum) if maximum > 0 else None


def _function_name(defs: Definitions, function: str | None) -> str:
    taxonomy = defs.bodies("taxonomy").get("default") or {}
    names = {str(f.get("id")): str(f.get("name")) for f in taxonomy.get("functions") or []}
    return names.get(str(function), str(function or "")) if function else ""


def pack_of(
    defs: Definitions,
    version: registry.Version,
    installed: bool,
    sandboxed: SandboxForecast,
    *,
    detail: bool = False,
    cap_minor: int | None = None,
    reviewer_pool: str | None = None,
    installed_version: int | None = None,
    installed_listing_version: str | None = None,
) -> Pack:
    """A pack definition as the marketplace Pack (`detail` adds the input schema; `cap_minor` is the org's
    per-run cap from its hire, `reviewer_pool` its reviewer pool, `installed_version` the version it pins and
    `installed_listing_version` the approved listing version it holds). Another workspace's listed pack
    carries its listing (publisher, fee per run, update) and is not certified; only the platform's are."""
    body = version.body
    connectors = defs.bodies("connector")
    team = defs.is_team("pack", version.key)
    row = defs.listed.get(("pack", version.key))
    return Pack(
        slug=slug_of(version),
        name=str(body.get("name") or version.key),
        version=str(body.get("version") or version.version),
        publisher=row.publisher if row else str(body.get("publisher") or ""),
        category=_function_name(defs, body.get("function")),
        outcome=str(body.get("outcome") or ""),
        description=str(body.get("description") or ""),
        agents=[str(a) for a in body.get("agents") or []],
        connectors=pack_connectors(
            [str(c) for c in body.get("connectors") or []],
            connectors,
            sandboxed,
            contract_of(defs, body),
        ),
        human_review=str(body.get("human_review") or ""),
        estimate=_estimate(contract_of(defs, body)),
        max_budget=max_budget(contract_of(defs, body)),
        installed=installed,
        certified=not team and row is None and not owners.is_reserved(version.key),
        risk_class=body.get("risk_class")
        if body.get("risk_class") in ("low", "medium", "high")
        else "medium",
        regions=[workspace.REGION],
        function=body.get("function"),
        industries=[str(i) for i in body.get("industries") or []],
        price_note=None if row else (str(body.get("price_note") or "") or None),
        input_schema=input_schema(defs, body) if detail else None,
        per_run_cap=Money(amount_minor=cap_minor) if installed and cap_minor is not None else None,
        reviewer_pool=reviewer_pool if installed else None,
        built_by_team=True if team else None,
        copyable=True if team or (row is None and not owners.is_reserved(version.key)) else None,
        listing=market_listing(
            row,
            "run",
            installed_version if installed else None,
            installed_listing_version if installed else None,
        )
        if row
        else None,
    )


def _hires(org_id: str) -> dict[str, dict]:
    """The org's added packs, by slug: {cap_minor, pack_version, listing_version_id}, from one read."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT pack_slug, cap_minor, pack_version, listing_version_id FROM installations "
            "WHERE org_id = %s",
            (org_id,),
        ).fetchall()
    return {r["pack_slug"]: r for r in rows}


def installation(org_id: str, slug: str) -> dict | None:
    """The org's hire of the pack ({cap_minor, reviewer_pool, pack_version, listing_version_id}), None when
    not hired."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT cap_minor, reviewer_pool, pack_version, listing_version_id FROM installations "
            "WHERE org_id = %s AND pack_slug = %s",
            (org_id, slug),
        ).fetchone()


def is_installed(org_id: str, slug: str) -> bool:
    return installation(org_id, slug) is not None


def _visible(pack_listings: dict[str, PackListing], slug: str, installed: bool) -> bool:
    """The Ops listing's marketplace effect, as in the demo workspace: no listing or published is shown, a
    deprecated pack only to an org that has hired it, any other status is hidden."""
    listing = pack_listings.get(slug)
    if listing is None or listing.status == "published":
        return True
    return listing.status == "deprecated" and installed


def _listings() -> dict[str, PackListing]:
    with locked_store() as store:
        return dict(store.pack_listings)


def list_packs(org_id: str) -> list[Pack]:
    defs, hired, pack_listings = definitions(org_id), _hires(org_id), _listings()
    sandboxed = SandboxForecast.for_org(org_id)
    out = []
    for v in defs.packs():
        hire = hired.get(slug_of(v))
        if not _visible(pack_listings, slug_of(v), hire is not None):
            continue
        pack = pack_of(
            defs,
            v,
            hire is not None,
            sandboxed,
            cap_minor=hire["cap_minor"] if hire else None,
            installed_version=int(hire["pack_version"]) if hire else None,
            installed_listing_version=hire["listing_version_id"] if hire else None,
        )
        out.append((pack, v.key, hire))
    if not hired:
        return [p for p, _, _ in out]
    with db.connect() as conn:
        return [p.model_copy(update=_run_terms(conn, org_id, p, key, hire)) for p, key, hire in out]


def _run_terms(conn, org_id: str, pack: Pack, key: str, hire: dict | None) -> dict:
    """An added pack's `run_fee` (the pack fee a run pays up front, at the listing version the installation
    holds, as the start charges it) and `run_budget_limit`, the most a run may be given now: within the
    pack's maximum and, with the fee on top, within the per-run cap. Empty for a pack not added."""
    if hire is None or hire["cap_minor"] is None:
        return {}
    version, held = int(hire["pack_version"]), hire["listing_version_id"]
    fee = fees.pack_fee_minor(conn, org_id, key, version, held) if pack.listing else 0
    room = int(hire["cap_minor"]) - fee
    if pack.max_budget is not None:
        room = min(room, pack.max_budget.amount_minor)
    return {"run_fee": Money(amount_minor=fee), "run_budget_limit": Money(amount_minor=max(room, 0))}


def _find(defs: Definitions, org_id: str, slug: str) -> tuple[registry.Version, bool]:
    """(pack definition, hired by the org); 404 when there is none the org may see."""
    version = defs.pack(slug)
    hired = version is not None and is_installed(org_id, slug_of(version))
    if version is None or not _visible(_listings(), slug_of(version), hired):
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    return version, hired


def get_pack(org_id: str, slug: str) -> Pack:
    defs = definitions(org_id)
    version, hired = _find(defs, org_id, slug)
    hire = installation(org_id, slug_of(version)) if hired else None
    cap = hire["cap_minor"] if hire else None
    pool = hire["reviewer_pool"] if hire else None
    sandboxed = SandboxForecast.for_org(org_id)
    pack = pack_of(
        defs,
        version,
        hired,
        sandboxed,
        detail=True,
        cap_minor=cap,
        reviewer_pool=pool,
        installed_version=int(hire["pack_version"]) if hire else None,
        installed_listing_version=hire["listing_version_id"] if hire else None,
    )
    if pack.listing is not None and pack.listing.update_available:
        held = _held_terms(defs, org_id, version, sandboxed)
        pack = pack.model_copy(update=held) if held else pack
    if hire is None:
        return pack
    with db.connect() as conn:
        return pack.model_copy(update=_run_terms(conn, org_id, pack, version.key, hire))


def _held_terms(
    defs: Definitions, org_id: str, version: registry.Version, sandboxed: SandboxForecast
) -> dict | None:
    """What a run of the version an installation of another workspace's listed pack holds would use, when a
    newer one is approved: its start form (`input_schema`, the schema the run is checked against), its
    budget estimate and its connectors. None when the installation's version cannot run now (the start
    answers PACK_UNAVAILABLE)."""
    slug = slug_of(version)
    try:
        with db.connect() as conn:
            pins = listing_pins.installed_pins(conn, org_id, slug)
            if not pins:
                return None
            schema = listing_pins.pinned_input_schema(conn, org_id, slug, pins)
            held = [registry.get_version(conn, kind, key, v) for (kind, key), v in sorted(pins.items())]
    except listing_pins.Unavailable:
        return None
    by_kind = {kind: dict(versions) for kind, versions in defs.by_kind.items()}
    for v in held:
        if v is not None:
            by_kind.setdefault(v.kind, {})[v.key] = v
    pinned = replace(defs, by_kind=by_kind)
    body = by_kind["pack"][version.key].body
    return {
        "input_schema": schema,
        "estimate": _estimate(contract_of(pinned, body)),
        "max_budget": max_budget(contract_of(pinned, body)),
        "connectors": pack_connectors(
            [str(c) for c in body.get("connectors") or []],
            pinned.bodies("connector"),
            sandboxed,
            contract_of(pinned, body),
        ),
    }


# --- suggest --------------------------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    """Lower-case words of three letters or more without stop words, a plural "s" dropped."""
    out = set()
    for word in _WORD.findall(text.lower()):
        if len(word) < 3 or word in _STOP_WORDS:
            continue
        out.add(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word)
    return out


def _pack_words(defs: Definitions, body: dict) -> set[str]:
    taxonomy = defs.bodies("taxonomy").get("default") or {}
    industry_names = {str(i.get("id")): str(i.get("name")) for i in taxonomy.get("industries") or []}
    industries = [str(i) for i in body.get("industries") or []]
    text = " ".join(
        [str(body.get(f) or "") for f in ("name", "outcome", "description")]
        + [i.replace("-", " ") for i in industries]
        + [industry_names.get(i, "") for i in industries]
    )
    return _words(text)


def suggest(org_id: str, text: str) -> Suggestion:
    """The listed pack definition whose name, outcome, description and industries share the most words with
    `text`. A keyword match over real definitions, so not simulated."""
    defs, hired, pack_listings = definitions(org_id), _hires(org_id), _listings()
    asked = _words(text)
    scored = [
        (len(asked & _pack_words(defs, v.body)), slug_of(v), v)
        for v in defs.packs()
        if _visible(pack_listings, slug_of(v), slug_of(v) in hired)
    ]
    best = min(scored, key=lambda s: (-s[0], s[1]), default=None)  # most shared words, then by slug
    if best is None or best[0] == 0:
        return Suggestion(
            steps=["Describe the result you want, the apps involved and how often."], simulated=False
        )
    sandboxed = SandboxForecast.for_org(org_id)
    hire = hired.get(best[1])
    pack = pack_of(
        defs,
        best[2],
        hire is not None,
        sandboxed,
        cap_minor=hire["cap_minor"] if hire else None,
        installed_version=int(hire["pack_version"]) if hire else None,
        installed_listing_version=hire["listing_version_id"] if hire else None,
    )
    steps = [
        f"Read the data it needs from {', '.join(c.app for c in pack.connectors)}.",
        pack.outcome,
        f"A person steps in when needed: {pack.human_review.lower()}",
        "An independent check verifies the result before you accept it.",
    ]
    return Suggestion(pack=pack, steps=steps, simulated=False)


# --- install --------------------------------------------------------------------------------------------


def _refuse_taken_name(conn, org_id: str, slug: str, name: str) -> None:
    """409 CONFLICT when another pack the org added (a listed one under the name of the version it holds) has
    the name `name` (any case): grants are keyed by pack name, so two added packs of one name would share
    them. A pack the org has not added holds no grants and never blocks a name."""
    names = live_connections.added_names(conn, org_id)
    taken = {n.strip().casefold() for s, n in names.items() if s != slug}
    if name.strip().casefold() in taken:
        raise ApiProblem(
            409,
            "CONFLICT",
            f"A pack you've added already uses the name {name.strip()}. App permissions are kept by pack "
            "name, so two of your packs can't share one.",
        )


def _foreign_pack(conn, org_id: str, key: str) -> bool:
    """Whether pack `key` is another workspace's private one: the org reaches it only by its listing."""
    owner = registry.owner_of(conn, "pack", key)
    return owner.visibility == "private" and owner != owners.org_owner(org_id)


def _first_pin(conn, org_id: str, latest: registry.Version, slug: str) -> tuple[registry.Version, str | None]:
    """(pack version, listing version) a first hire pins: `latest` (the version the org may use), with the
    approved listing version it is listed at for another workspace's listed pack (None for the platform's
    packs and the org's own). 404 when the listing changed or went since `latest` was read, so no listed
    pack is added without the listing version it holds; 409 CONFLICT when its name is taken
    (`_refuse_taken_name`)."""
    market = listings.market_info(conn, org_id).get(("pack", latest.key))
    gone = market is None and _foreign_pack(conn, org_id, latest.key)
    if gone or (market is not None and market.version != latest.version):
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    _refuse_taken_name(conn, org_id, slug, str(latest.body.get("name") or slug))
    return latest, market.version_id if market else None


def install(actor: Actor, body: InstallRequest) -> Installation:
    """Hire the pack for the actor's org, or save an existing hire's settings: insert or update its
    installations row (idempotent), and give the org's apps already connected the grants this pack uses.
    A first hire pins the version the org may use (`registry.visible_version`): the latest of the platform's
    packs and the org's own, the approved one of another workspace's listed pack, with the listing version it
    is approved in (`installations.listing_version_id`). Saving settings keeps both pins: a listed pack moves
    on only through `upgrade`. 409 CONFLICT for a first hire whose name another pack has.
    Saving the pool as `team` returns the open tasks of the org's runs of this pack that network reviewers
    claimed to the queue, so only the team holds them. Never touches the demo store."""
    defs = definitions(actor.org_id)
    latest, _ = _find(defs, actor.org_id, body.pack_slug)
    slug = slug_of(latest)
    pool = body.reviewer_pool
    with db.connect() as conn:
        # The org row first, then its tasks: the lock order of `app.review_routing`. A claim in flight holds
        # the org FOR SHARE, so this waits for it and then releases it; a claim that waits here reads the
        # new pool once this commits.
        org = conn.execute(
            "SELECT allow_network FROM orgs WHERE id = %s FOR NO KEY UPDATE", (actor.org_id,)
        ).fetchone()
        # Under the registry lock the pack is read again: a save in flight lands before or after this hire,
        # never between the read above and the pin, so a first hire never pins a version just replaced.
        registry.lock(conn)
        latest = registry.visible_version(conn, "pack", latest.key, actor.org_id)
        if latest is None:  # a listing withdrawn since the read above
            raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {body.pack_slug}.")
        hire = conn.execute(
            "SELECT pack_version FROM installations WHERE org_id = %s AND pack_slug = %s FOR UPDATE",
            (actor.org_id, slug),
        ).fetchone()
        if hire is None:
            version, held = _first_pin(conn, actor.org_id, latest, slug)
        else:  # a pin the registry no longer has falls back to `latest` for its body; the pin is kept
            version = registry.get_version(conn, "pack", latest.key, hire["pack_version"]) or latest
            held = None  # not written: the listing version held stays
        conn.execute(
            "INSERT INTO installations (org_id, pack_slug, pack_version, listing_version_id, cap_minor, "
            "reviewer_pool, installed_by) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (org_id, pack_slug) DO UPDATE SET "
            "cap_minor = EXCLUDED.cap_minor, reviewer_pool = EXCLUDED.reviewer_pool",
            (actor.org_id, slug, version.version, held, body.cap_minor, pool, actor.user_id),
        )
        # The contract of the pinned version (of a listed pack, its approved bundle's): grants nothing without
        # one, and never the capabilities of a newer approved version the org has not updated to.
        contract = live_connections.pinned_contract(conn, actor.org_id, version)
        contracts = {contract.key: contract.body} if contract else {}
        live_connections.grant_pack(conn, defs.bodies("connector"), actor.org_id, version.body, contracts)
        if pool == "team":
            run_tasks.release_claims(conn, org_id=actor.org_id, pack_slug=slug, via="network")
        conn.commit()
    return Installation(
        pack_slug=slug,
        cap_minor=body.cap_minor,
        reviewer_pool=pool,
        summary=hire_summary(body.cap_minor, pool, network_on=bool(org and org["allow_network"])),
    )


def _runs_in_progress(conn, org_id: str, slug: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM runs WHERE org_id = %s AND pack_slug = %s AND status <> ALL(%s) LIMIT 1",
        (org_id, slug, sorted(TERMINAL_RUN_STATUSES)),
    ).fetchone()
    return row is not None


def upgrade(actor: Actor, slug: str) -> Installation:
    """Move the org's installation of another workspace's listed pack to its current approved listing version
    (and its pack version), for future runs (and so their fee). A version approved again at the same pack
    version is an update too. Every check comes before any write: 404 NOT_FOUND for a pack the org cannot
    see; 409 PACK_NOT_HIRED, NOT_LISTED (the platform's packs and the org's own have no updates),
    UP_TO_DATE, RUNS_IN_PROGRESS (a run finds its grants by the pack name its snapshot pinned), CONFLICT
    (the new name is another pack's). The connection grants (and revocations) then follow a rename and are
    recomputed for the new version. Lock order as `install`: org, installation, (org, app)."""
    defs = definitions(actor.org_id)
    found = defs.pack(slug)
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    key, name, slug = found.key, str(found.body.get("name") or slug), slug_of(found)
    with db.connect() as conn:
        org = conn.execute(
            "SELECT allow_network FROM orgs WHERE id = %s FOR NO KEY UPDATE", (actor.org_id,)
        ).fetchone()
        hire = conn.execute(
            "SELECT pack_version, listing_version_id, cap_minor, reviewer_pool FROM installations "
            "WHERE org_id = %s AND pack_slug = %s FOR UPDATE",
            (actor.org_id, slug),
        ).fetchone()
        if hire is None:
            raise ApiProblem(409, "PACK_NOT_HIRED", f"Add {name} before updating it.")
        market = listings.market_info(conn, actor.org_id).get(("pack", key))
        new = registry.visible_version(conn, "pack", key, actor.org_id) if market else None
        if market is None or new is None or new.version != market.version:
            raise ApiProblem(
                409, "NOT_LISTED", f"{name} is not listed by another workspace, so it has no updates."
            )
        if hire["listing_version_id"] == market.version_id:  # one holding none can update to get one
            raise ApiProblem(409, "UP_TO_DATE", f"{name} is already at its newest version.")
        if _runs_in_progress(conn, actor.org_id, slug):
            raise ApiProblem(
                409, "RUNS_IN_PROGRESS", f"Wait for the runs of {name} to finish, then update it."
            )
        old = registry.get_version(conn, "pack", key, int(hire["pack_version"])) or new
        old_name, new_name = (str(v.body.get("name") or key) for v in (old, new))
        _refuse_taken_name(conn, actor.org_id, slug, new_name)
        conn.execute(
            "UPDATE installations SET pack_version = %s, listing_version_id = %s "
            "WHERE org_id = %s AND pack_slug = %s",
            (new.version, market.version_id, actor.org_id, slug),
        )
        used = {str(c) for v in (old, new) for c in v.body.get("connectors") or []}
        if old_name != new_name:  # grants and revocations are keyed by pack name; connections by connector
            for connector in sorted(used):
                live_connections.rename_install(conn, actor.org_id, connector, old_name, new_name)
        # Recomputed from the new pin: the grants match the new version, dropped ones go, revoked ones stay.
        live_connections.regrant(conn, defs.bodies("connector"), actor.org_id, used)
        conn.commit()
    cap, pool = int(hire["cap_minor"]), str(hire["reviewer_pool"])
    return Installation(
        pack_slug=slug,
        cap_minor=cap,
        reviewer_pool=pool,
        summary=hire_summary(cap, pool, network_on=bool(org and org["allow_network"])),
    )
