"""The live workspace marketplace: every pack definition is a Workflow Pack, hired per org in the
`installations` table. Reads the latest definitions from the Postgres registry (the live workspace always has
the runtime on) and never the demo fixtures. Every installation query is scoped to one org."""

import re
from dataclasses import dataclass

from app import db, live_connections, run_tasks, workspace
from app.auth import Actor
from app.catalog.packs import SandboxForecast, pack_connectors
from app.defs import registry
from app.errors import ApiProblem
from app.models.catalog import Pack, PackEstimate, Suggestion
from app.models.common import Money
from app.models.ops import PackListing
from app.models.requests import Installation, InstallRequest
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
    """The latest version of every definition, by kind and key."""

    by_kind: dict[str, dict[str, registry.Version]]

    def bodies(self, kind: str) -> dict[str, dict]:
        return {key: v.body for key, v in self.by_kind.get(kind, {}).items()}

    def pack(self, slug: str) -> registry.Version | None:
        """The pack definition whose slug (or key) is `slug`."""
        packs = self.by_kind.get("pack", {})
        found = next((v for v in packs.values() if v.body.get("slug") == slug), None)
        return found or packs.get(slug)

    def packs(self) -> list[registry.Version]:
        return [v for _, v in sorted(self.by_kind.get("pack", {}).items())]


def definitions() -> Definitions:
    with db.connect() as conn:
        versions = registry.latest_all(conn)
    by_kind: dict[str, dict[str, registry.Version]] = {}
    for v in versions:
        by_kind.setdefault(v.kind, {})[v.key] = v
    return Definitions(by_kind)


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
) -> Pack:
    """A pack definition as the marketplace Pack (`detail` adds the input schema; `cap_minor` is the org's
    per-run cap from its hire, and `reviewer_pool` its reviewer pool)."""
    body = version.body
    connectors = defs.bodies("connector")
    return Pack(
        slug=slug_of(version),
        name=str(body.get("name") or version.key),
        version=str(body.get("version") or version.version),
        publisher=str(body.get("publisher") or ""),
        category=_function_name(defs, body.get("function")),
        outcome=str(body.get("outcome") or ""),
        description=str(body.get("description") or ""),
        agents=[str(a) for a in body.get("agents") or []],
        connectors=pack_connectors([str(c) for c in body.get("connectors") or []], connectors, sandboxed),
        human_review=str(body.get("human_review") or ""),
        estimate=_estimate(contract_of(defs, body)),
        installed=installed,
        certified=True,
        risk_class=body.get("risk_class")
        if body.get("risk_class") in ("low", "medium", "high")
        else "medium",
        regions=[workspace.REGION],
        function=body.get("function"),
        industries=[str(i) for i in body.get("industries") or []],
        price_note=str(body.get("price_note") or "") or None,
        input_schema=input_schema(defs, body) if detail else None,
        per_run_cap=Money(amount_minor=cap_minor) if installed and cap_minor is not None else None,
        reviewer_pool=reviewer_pool if installed else None,
    )


def installed_slugs(org_id: str) -> dict[str, int]:
    """The org's hired packs: slug to per-run cap in minor units."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT pack_slug, cap_minor FROM installations WHERE org_id = %s", (org_id,)
        ).fetchall()
    return {r["pack_slug"]: r["cap_minor"] for r in rows}


def installation(org_id: str, slug: str) -> dict | None:
    """The org's hire of the pack ({cap_minor, reviewer_pool, pack_version}), None when not hired."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT cap_minor, reviewer_pool, pack_version FROM installations "
            "WHERE org_id = %s AND pack_slug = %s",
            (org_id, slug),
        ).fetchone()


def is_installed(org_id: str, slug: str) -> bool:
    return installation(org_id, slug) is not None


def _visible(listings: dict[str, PackListing], slug: str, installed: bool) -> bool:
    """The Ops listing's marketplace effect, as in the demo workspace: no listing or published is shown, a
    deprecated pack only to an org that has hired it, any other status is hidden."""
    listing = listings.get(slug)
    if listing is None or listing.status == "published":
        return True
    return listing.status == "deprecated" and installed


def _listings() -> dict[str, PackListing]:
    with locked_store() as store:
        return dict(store.pack_listings)


def list_packs(org_id: str) -> list[Pack]:
    defs, hired, listings = definitions(), installed_slugs(org_id), _listings()
    sandboxed = SandboxForecast()
    return [
        pack_of(defs, v, slug_of(v) in hired, sandboxed, cap_minor=hired.get(slug_of(v)))
        for v in defs.packs()
        if _visible(listings, slug_of(v), slug_of(v) in hired)
    ]


def _find(defs: Definitions, org_id: str, slug: str) -> tuple[registry.Version, bool]:
    """(pack definition, hired by the org); 404 when there is none the org may see."""
    version = defs.pack(slug)
    hired = version is not None and is_installed(org_id, slug_of(version))
    if version is None or not _visible(_listings(), slug_of(version), hired):
        raise ApiProblem(404, "NOT_FOUND", f"No Workflow Pack called {slug}.")
    return version, hired


def get_pack(org_id: str, slug: str) -> Pack:
    defs = definitions()
    version, hired = _find(defs, org_id, slug)
    hire = installation(org_id, slug_of(version)) if hired else None
    cap = hire["cap_minor"] if hire else None
    pool = hire["reviewer_pool"] if hire else None
    return pack_of(defs, version, hired, SandboxForecast(), detail=True, cap_minor=cap, reviewer_pool=pool)


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
    defs, hired, listings = definitions(), installed_slugs(org_id), _listings()
    asked = _words(text)
    scored = [
        (len(asked & _pack_words(defs, v.body)), slug_of(v), v)
        for v in defs.packs()
        if _visible(listings, slug_of(v), slug_of(v) in hired)
    ]
    best = min(scored, key=lambda s: (-s[0], s[1]), default=None)  # most shared words, then by slug
    if best is None or best[0] == 0:
        return Suggestion(
            steps=["Describe the result you want, the apps involved and how often."], simulated=False
        )
    pack = pack_of(defs, best[2], best[1] in hired, SandboxForecast(), cap_minor=hired.get(best[1]))
    steps = [
        f"Read the data it needs from {', '.join(c.app for c in pack.connectors)}.",
        pack.outcome,
        f"A person steps in when needed: {pack.human_review.lower()}",
        "An independent check verifies the result before you accept it.",
    ]
    return Suggestion(pack=pack, steps=steps, simulated=False)


# --- install --------------------------------------------------------------------------------------------


def _pinned_version(conn, latest: registry.Version, org_id: str, slug: str) -> registry.Version:
    """The pack version the org's hire is pinned to (locked for the update), or `latest` for a first hire.
    A pin the registry no longer has falls back to `latest` for its body; the pin itself is kept."""
    row = conn.execute(
        "SELECT pack_version FROM installations WHERE org_id = %s AND pack_slug = %s FOR UPDATE",
        (org_id, slug),
    ).fetchone()
    if row is None:
        return latest
    return registry.get_version(conn, "pack", latest.key, row["pack_version"]) or latest


def install(actor: Actor, body: InstallRequest) -> Installation:
    """Hire the pack for the actor's org, or save an existing hire's settings: insert or update its
    installations row (idempotent), and give the org's apps already connected the grants this pack uses.
    A first hire pins the latest version; saving settings keeps the pin (updates need their own approval).
    Saving the pool as `team` returns the open tasks of the org's runs of this pack that network reviewers
    claimed to the queue, so only the team holds them. Never touches the demo store."""
    defs = definitions()
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
        version = _pinned_version(conn, latest, actor.org_id, slug)
        conn.execute(
            "INSERT INTO installations (org_id, pack_slug, pack_version, cap_minor, reviewer_pool, "
            "installed_by) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (org_id, pack_slug) DO UPDATE SET "
            "cap_minor = EXCLUDED.cap_minor, reviewer_pool = EXCLUDED.reviewer_pool",
            (actor.org_id, slug, version.version, body.cap_minor, pool, actor.user_id),
        )
        live_connections.grant_pack(
            conn, defs.bodies("connector"), actor.org_id, version.body, defs.bodies("contract")
        )
        if pool == "team":
            run_tasks.release_claims(conn, org_id=actor.org_id, pack_slug=slug, via="network")
        conn.commit()
    return Installation(
        pack_slug=slug,
        cap_minor=body.cap_minor,
        reviewer_pool=pool,
        summary=hire_summary(body.cap_minor, pool, network_on=bool(org and org["allow_network"])),
    )
