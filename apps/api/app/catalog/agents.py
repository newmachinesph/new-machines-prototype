"""The customer agent catalog: agent definitions (plus, in the demo workspace, the sample fixture agents) with
the skills, tools and model profile each one runs with and the packs that use it."""

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import NamedTuple

from app.defs.current import latest_bodies, latest_with_files, team_keys
from app.models.catalog import Agent, AgentPackRef, AgentSkill, SampleAgent

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


def definition_agent(
    key: str, body: dict, files: dict[str, str], packs: Iterable[PackUse], *, team: bool = False
) -> Agent:
    runtime = body.get("runtime") if isinstance(body.get("runtime"), dict) else {}
    processing = body.get("data_processing") if isinstance(body.get("data_processing"), dict) else {}
    profile = runtime.get("model_profile")
    skills = _strings(runtime.get("skills"))
    return Agent(
        id=key,
        version=str(body.get("version") or ""),
        name=agent_name(key, body),
        publisher=str(
            body.get("publisher_name") or humanise(str(body.get("publisher_id") or ""), title=True)
        ),
        summary=str(body.get("summary") or ""),
        capabilities=_strings(body.get("capabilities")),
        regions=_strings(processing.get("supported_regions")),
        certified=not team,
        skills=[AgentSkill(key=PurePosixPath(p).stem, title=skill_title(p, files.get(p))) for p in skills],
        tools=_strings(runtime.get("tools")),
        model_profile=profile if profile in MODEL_PROFILES else None,
        used_by=_used_by(key, packs),
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
    `org_id` (live workspace) the org's own agents are included, marked built by its team."""
    team = team_keys(org_id)
    defined = [
        definition_agent(key, body, files, packs, team=("agent", key) in team)
        for key, (body, files) in sorted(latest_with_files("agent", org_id).items())
    ]
    hidden = {a.id for a in defined} | set(aliases or {})
    return defined + [sample_agent(a, packs) for a in samples if a.id not in hidden]
