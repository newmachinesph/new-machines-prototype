"""The Studio (sub-project C): what an org's builders send and get back when they make their own agents and
Workflow Packs. Drafts are request models (sent back on every save); the responses embed them, so they stay
request models with `additionalProperties: false`."""

from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.models.common import Model, Opt, RequestModel
from app.models.publishing import MarketplaceListing

ModelProfile = Literal["reasoning", "fast"]
StepType = Literal[
    "trigger",
    "memory",
    "connector",
    "agent",
    "decision",
    "human_workforce",
    "approval",
    "verification",
    "end",
]
FieldType = Literal["text", "date", "number"]
Verdict = Literal["APPROVED", "HUMAN_REVIEW", "BLOCKED", "REJECTED"]
# A step id is a CEL identifier (`nodes.<id>.output`), so it has no hyphen.
STEP_ID = r"^[a-z][a-z0-9_]{0,39}$"
ToolRef = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")]
SINGLE_LINE = r"^[^\r\n]+$"
# Text is stripped before the length check, so a whitespace-only field is refused on save rather than failing
# `agent_draft` when the saved agent is read back.
STRIPPED = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SkillDraft(RequestModel):
    model_config = STRIPPED

    title: str = Field(min_length=1, max_length=80, pattern=SINGLE_LINE)
    text: str = Field(min_length=1, max_length=8000)


class AgentDraft(RequestModel):
    """An agent as the Studio edits it. Tools are app tools that only read."""

    model_config = STRIPPED

    name: str = Field(min_length=1, max_length=80, pattern=SINGLE_LINE)
    summary: str = Field(min_length=1, max_length=280, pattern=SINGLE_LINE)
    instructions: str = Field(min_length=1, max_length=12000)
    model_profile: ModelProfile = "reasoning"
    skills: list[SkillDraft] = Field(default_factory=list, max_length=10)
    tools: list[ToolRef] = Field(default_factory=list, max_length=12)
    max_turns: int = Field(default=6, ge=1, le=20)


class SaveAgentRequest(RequestModel):
    """`base_version` is the version the edit started from; 409 VERSION_CONFLICT when someone saved since."""

    draft: AgentDraft
    base_version: int | Opt = Field(default=None, ge=1)


class InputField(RequestModel):
    """One field of the run's start form."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    type: FieldType = "text"
    required: bool = True


class DecisionRule(RequestModel):
    """`when` is CEL over the run state; the first rule that is true picks the route."""

    when: str = Field(min_length=1, max_length=2000)
    route: str = Field(pattern=STEP_ID)
    verdict: Verdict = "APPROVED"
    explanation: str = Field(min_length=1, max_length=400)


class DecisionDefault(RequestModel):
    route: str = Field(pattern=STEP_ID)
    verdict: Verdict = "HUMAN_REVIEW"
    explanation: str = Field(min_length=1, max_length=400)


class DecisionRules(RequestModel):
    question: str = Field(min_length=1, max_length=200)
    rules: list[DecisionRule] = Field(default_factory=list, max_length=20)
    default: DecisionDefault


class StepDraft(RequestModel):
    """One workflow node. `config` is the node's config as the runtime reads it (strings starting with "="
    are CEL); `routes` maps each outcome to the next step. A decision keeps its rules in `rules`."""

    id: str = Field(pattern=STEP_ID)
    type: StepType
    config: dict[str, Any] = Field(default_factory=dict)
    routes: dict[str, str] = Field(default_factory=dict)
    rules: DecisionRules | Opt = None


class PackDraft(RequestModel):
    """A Workflow Pack as the Studio edits it: what the marketplace shows, the start form, the budget and
    the steps."""

    name: str = Field(min_length=1, max_length=80)
    outcome: str = Field(min_length=1, max_length=280)
    description: str = Field(min_length=1, max_length=2000)
    human_review: str = Field(min_length=1, max_length=400)
    function: str = Field(default="finance-ops", min_length=1, max_length=40)
    industries: list[str] = Field(default_factory=lambda: ["retail-commerce"], min_length=1, max_length=5)
    input_fields: list[InputField] = Field(default_factory=list, max_length=10)
    budget_minor: int = Field(default=1500, ge=100, le=100_000)
    human_budget_minor: int = Field(default=0, ge=0, le=100_000)
    entry_step: str = Field(pattern=STEP_ID)
    steps: list[StepDraft] = Field(min_length=2, max_length=60)


class SavePackRequest(RequestModel):
    draft: PackDraft
    base_version: int | Opt = Field(default=None, ge=1)


class ImportWorkflowRequest(RequestModel):
    """A workflow.yaml, such as one exported from a pack."""

    yaml: str = Field(min_length=1, max_length=200_000)


class SandboxRunRequest(RequestModel):
    """The run input (checked against the pack's input schema) and an optional budget; the pack's maximum
    when omitted."""

    input: dict[str, Any] = Field(default_factory=dict)
    budget_minor: int | Opt = Field(default=None, gt=0, le=100_000)


class StudioAgentSummary(Model):
    key: str
    name: str
    summary: str
    model_profile: str
    version: int
    published_at: str
    used_by: list[str]  # names of the packs the org may see that use this agent


class StudioAgent(Model):
    key: str
    version: int
    published_at: str
    published_by: str
    draft: AgentDraft


class StudioPackSummary(Model):
    key: str
    name: str
    outcome: str
    version: int
    published_at: str
    steps: int
    added: bool  # the org has added the pack from its marketplace


class StudioPack(Model):
    key: str
    version: int
    published_at: str
    published_by: str
    draft: PackDraft
    added: bool


class BuilderIssue(Model):
    """One problem in a draft. `step` names the step it is about, when it is about one."""

    path: str
    message: str
    step: str | Opt = None


class BuilderCheck(Model):
    ok: bool
    issues: list[BuilderIssue]


class WorkflowYaml(Model):
    yaml: str


class ImportedWorkflow(Model):
    """The steps read from a workflow.yaml, and what could not be read."""

    entry_step: str
    steps: list[StepDraft]
    issues: list[BuilderIssue]


class PaletteAgent(Model):
    key: str
    name: str
    summary: str
    built_by_team: bool | Opt = None
    model_profile: str | Opt = None
    output_schema_ref: str
    output_schema: dict[str, Any] | Opt = None  # for the field picker: nodes.<id>.output.<field>
    listing: MarketplaceListing | Opt = None


class PaletteTool(Model):
    ref: str  # <connector>.<tool id>
    app: str
    name: str
    description: str
    action_class: str  # read | write | delete | money
    capability: str
    input_schema: dict[str, Any]


class PaletteSpace(Model):
    key: str
    name: str


class PaletteSchema(Model):
    key: str
    title: str
    body: dict[str, Any]


class Palette(Model):
    """What a pack's steps can use, from the registry: agents, app tools, memory and result shapes."""

    agents: list[PaletteAgent]
    tools: list[PaletteTool]
    spaces: list[PaletteSpace]
    schemas: list[PaletteSchema]
