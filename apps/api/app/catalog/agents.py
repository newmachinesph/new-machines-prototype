"""The customer agent catalog: agent definitions (plus, in the demo workspace, the sample fixture agents) with
the skills, tools and model profile each one runs with and the packs that use it."""

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import NamedTuple

from app import db, listings, settings
from app.defs import owners
from app.defs.current import latest_bodies, latest_with_files, team_keys
from app.models.catalog import Agent, AgentPackRef, AgentSkill, SampleAgent
from app.models.common import Money
from app.models.publishing import FeeUnit, MarketplaceListing

MODEL_PROFILES = ("reasoning", "fast")
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")


class PackUse(NamedTuple):
    """A pack as the catalog shows it: its slug, name and the agents its `agents` list names."""

    slug: str
    name: str
    agents: list[str]


def humanise(slug: str, *, title: bool = False) -> str:
    """`new-machines-labs` -> "New machines labs" (or "New Machines Labs" with `title`)."""
    words = [w for w in re.split(r"[-_\s]+", slug) if w]
    if title:
        return " ".join(w[:1].upper() + w[1:] for w in words)
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def skill_title(path: str, text: str | None) -> str:
    """The first Markdown heading of a skill file (front matter and code blocks skipped), else its file stem
    humanised."""
    if text:
        body = _FRONT_MATTER.sub("", text.replace("\r\n", "\n"), count=1)
        fenced = False
        for line in body.splitlines():
            if _FENCE.match(line):
                fenced = not fenced
            elif not fenced and (m := _HEADING.match(line)):
                return m.group(1)
    return humanise(PurePosixPath(path).stem)


def _strings(value: object) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _used_by(agent_id: str, packs: Iterable[PackUse]) -> list[AgentPackRef]:
    return [AgentPackRef(slug=p.slug, name=p.name) for p in packs if agent_id in p.agents]


def agent_name(key: str, body: dict) -> str:
    """A definition agent's customer-facing name: `name`, else its key humanised."""
    return str(body.get("name") or humanise(key, title=True))


def _fold(name: str) -> str:
    return " ".join(name.lower().split())


def sample_aliases(samples: list[SampleAgent]) -> dict[str, str]:
    """{sample id: definition key} for demo sample agents named like a definition agent. Such a sample is the
    same agent seen through older fixtures, so it is folded into the definition agent: not listed on its
    own, and fixture packs that name it point at the definition agent."""
    keys = {_fold(agent_name(key, body)): key for key, body in sorted(latest_bodies("agent").items())}
    return {s.id: keys[_fold(s.name)] for s in samples if _fold(s.name) in keys and s.id not in keys.values()}


def market_listing(
    row: listings.MarketRow,
    unit: FeeUnit,
    installed_version: int | None,
    installed_listing_version: str | None = None,
) -> MarketplaceListing:
    """Another workspace's listed agent or pack as the marketplace shows it: publisher, fee per `unit` and the
    approved version (`installed_version` and `update_available` only for a pack the viewer has added). An
    update is available when the installation holds another approved listing version than the current one
    (`installed_listing_version`; one holding none cannot run and updates to hold one), so a version
    approved again at the same pack version is an update too."""
    update = None if installed_version is None else installed_listing_version != row.version_id
    return MarketplaceListing(
        listing_id=row.listing_id,
        publisher=row.publisher,
        fee=Money(amount_minor=row.price_minor),
        fee_unit=unit,
        version=row.version,
        installed_version=installed_version,
        update_available=update,
    )


def listed_agents(org_id: str | None) -> dict[str, listings.MarketRow]:
    """Every agent another workspace has listed, by key, as `org_id` sees it (none without an org or with the
    runtime off)."""
    if org_id is None or not settings.runtime_enabled():
        return {}
    with db.connect() as conn:
        market = listings.market_info(conn, org_id)
    return {key: row for (kind, key), row in market.items() if kind == "agent"}


def definition_agent(
    key: str,
    body: dict,
    files: dict[str, str],
    packs: Iterable[PackUse],
    *,
    team: bool = False,
    listed: listings.MarketRow | None = None,
) -> Agent:
    """A definition agent. `listed`: another workspace's listed agent, shown with its listing's publisher and
    per-call fee. Only the platform's agents are certified: neither the org's own nor another workspace's."""
    runtime = body.get("runtime") if isinstance(body.get("runtime"), dict) else {}
    processing = body.get("data_processing") if isinstance(body.get("data_processing"), dict) else {}
    profile = runtime.get("model_profile")
    skills = _strings(runtime.get("skills"))
    return Agent(
        id=key,
        version=str(body.get("version") or ""),
        name=agent_name(key, body),
        publisher=listed.publisher
        if listed
        else str(body.get("publisher_name") or humanise(str(body.get("publisher_id") or ""), title=True)),
        summary=str(body.get("summary") or ""),
        capabilities=_strings(body.get("capabilities")),
        regions=_strings(processing.get("supported_regions")),
        certified=not team and listed is None and not owners.is_reserved(key),
        skills=[AgentSkill(key=PurePosixPath(p).stem, title=skill_title(p, files.get(p))) for p in skills],
        tools=_strings(runtime.get("tools")),
        model_profile=profile if profile in MODEL_PROFILES else None,
        used_by=_used_by(key, packs),
        listing=market_listing(listed, "call", None) if listed else None,
        source="definition",
        built_by_team=True if team else None,
    )


def sample_agent(agent: SampleAgent, packs: Iterable[PackUse]) -> Agent:
    return Agent(
        **agent.model_dump(), skills=[], tools=[], used_by=_used_by(agent.id, packs), source="sample"
    )


def definition_pack_uses(org_id: str | None = None) -> list[PackUse]:
    """Every pack definition `org_id` may see, for the live workspace (whose marketplace is the pack
    definitions)."""
    return [
        PackUse(
            slug=str(body.get("slug") or key),
            name=str(body.get("name") or key),
            agents=_strings(body.get("agents")),
        )
        for key, body in sorted(latest_bodies("pack", org_id).items())
    ]


def catalog(
    packs: list[PackUse],
    samples: list[SampleAgent],
    aliases: dict[str, str] | None = None,
    org_id: str | None = None,
) -> list[Agent]:
    """Definition agents by key, then `samples` (pass none in the live workspace) except those folded into a
    definition agent by `aliases`. `packs` should already name definition keys in place of aliases. With
    `org_id` (live workspace) the org's own agents are included, marked built by its team, and the agents
    other workspaces have listed, with their listing."""
    team, listed = team_keys(org_id), listed_agents(org_id)
    defined = [
        definition_agent(key, body, files, packs, team=("agent", key) in team, listed=listed.get(key))
        for key, (body, files) in sorted(latest_with_files("agent", org_id).items())
    ]
    hidden = {a.id for a in defined} | set(aliases or {})
    return defined + [sample_agent(a, packs) for a in samples if a.id not in hidden]
