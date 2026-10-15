from typing import Any, Literal

from pydantic import Field

from app.models.common import Model, Money, Opt
from app.models.workforce import ReviewerPool


class SampleAgent(Model):
    """A demo-workspace agent from fixtures/agents.json."""

    id: str
    version: str
    name: str
    publisher: str
    summary: str
    capabilities: list[str]
    regions: list[str]
    certified: bool


class AgentSkill(Model):
    key: str  # the skill file's stem, e.g. "match-orders"
    title: str  # the skill's first Markdown heading, else the stem humanised


class AgentPackRef(Model):
    slug: str
    name: str


class Agent(SampleAgent):
    """A catalog agent. `source` is "definition" for an agent definition, "sample" for a demo fixture
    agent (sample agents have no skills, tools or model profile). `used_by` lists the packs whose `agents`
    name it."""

    skills: list[AgentSkill]
    tools: list[str]  # connector tools it may call, `<connector>.<tool>`
    model_profile: Literal["reasoning", "fast"] | Opt = None
    used_by: list[AgentPackRef]
    source: Literal["definition", "sample"]
    # Live workspace: an agent the caller's org built in the Studio. Only that org sees it.
    built_by_team: bool | Opt = None


class PassportResult(Model):
    label: str
    value: float
    note: str | Opt = None


class TrustPassport(Model):
    tested_on: str
    tested_by: str
    cohort: str
    sample_size: int
    results: list[PassportResult]
    limitations: list[str]
    retest_triggers: list[str]


class PackConnector(Model):
    app: str
    access: Literal["read", "write (approval)", "write"]
    mocked: bool | Opt = None


class PackEstimate(Model):
    ai_min: Money
    ai_max: Money
    human_max: Money


class Pack(Model):
    slug: str
    name: str
    version: str
    publisher: str
    category: str
    outcome: str
    description: str
    agents: list[str]
    connectors: list[PackConnector]
    human_review: str
    estimate: PackEstimate
    installed: bool
    certified: bool
    passport: TrustPassport | Opt = None
    risk_class: Literal["low", "medium", "high"]
    regions: list[str]
    runs30d: int | Opt = Field(default=None, alias="runs30d")
    # From the pack definition: a taxonomy function id and industry ids (none for packs without one).
    function: str | Opt = None
    industries: list[str] = Field(default_factory=list)
    # Live workspace (pack definitions): the pack's price note.
    price_note: str | Opt = None
    # On the detail response, the JSON Schema of the input a run takes: every live pack, and in the demo
    # workspace a pack that runs for real.
    input_schema: dict[str, Any] | Opt = None
    # Live workspace, hired packs only: the per-run spending cap the org set when it hired the pack.
    per_run_cap: Money | Opt = None
    # Live workspace, hired packs only: who reviews the hire's tasks.
    reviewer_pool: ReviewerPool | Opt = None
    # Live workspace: a pack the caller's org built in the Studio ("Built by your team"). Only that org sees
    # it, and it is not certified by New Machines.
    built_by_team: bool | Opt = None


class Suggestion(Model):
    pack: Pack | Opt = None
    steps: list[str]
    simulated: bool


class TaxonomyEntry(Model):
    id: str
    name: str


class Taxonomy(Model):
    functions: list[TaxonomyEntry]
    industries: list[TaxonomyEntry]
