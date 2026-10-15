from typing import Literal

from pydantic import Field

from app.models.common import Actor, Model, Money, Opt, StageState

RunStatus = Literal[
    "RUNNING",
    "WAITING_FOR_HUMAN",
    "WAITING_FOR_EVENT",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "NEEDS_ATTENTION",
]
NodeStatus = Literal[
    "CREATED",
    "READY",
    "RUNNING",
    "WAITING",
    "VALIDATING",
    "COMPLETED",
    "FAILED",
    "REJECTED",
    "TIMED_OUT",
    "CANCELLED",
    "COMPENSATING",
    "ESCALATED",
    "BLOCKED",
    "SKIPPED",
]
NodeType = Literal[
    "trigger",
    "connector",
    "parallel",
    "join",
    "agent",
    "decision",
    "human_workforce",
    "approval",
    "verification",
    "memory",
    "end",
]
DecisionVerdict = Literal[
    "APPROVED", "REJECTED", "REVISION_REQUIRED", "HUMAN_REVIEW", "ESCALATED", "ERROR", "TIMED_OUT", "BLOCKED"
]
PolicyVerdict = Literal["PERMIT", "DENY", "REQUIRE_APPROVAL"]
ToolStatus = Literal[
    "PLANNED", "AUTHORIZED", "SENT", "CONFIRMED", "DENIED", "FAILED", "UNCONFIRMED", "CANCELLED"
]


class Evaluator(Model):
    kind: Literal["rules", "gemini", "human", "jev"]
    label: str
    config_version: str
    model_id: str | Opt = None


class ChainStep(Model):
    kind: Literal["rules", "gemini", "jev"]
    verdict: DecisionVerdict | Literal["PASS"]
    note: str


class PolicyDecision(Model):
    id: str
    ref: str
    verdict: PolicyVerdict
    reason_codes: list[str]
    actor: str


class ApprovalRef(Model):
    id: str
    status: Literal["PENDING", "GRANTED", "NOT_REQUIRED"]
    by: str | Opt = None


class DecisionRecord(Model):
    question: str
    evaluator: Evaluator
    chain: list[ChainStep]
    verdict: DecisionVerdict
    reason_codes: list[str]
    explanation: str
    evidence_refs: list[str]
    route: str
    evaluated_at: str
    policy: PolicyDecision
    approval: ApprovalRef | Opt = None


class ToolCall(Model):
    id: str
    app: str
    action: str
    capability: str
    status: ToolStatus
    policy: PolicyVerdict
    detail: str
    mocked: bool | Opt = None
    # The tool's action class (read, write, money, ...) from its connector definition; real runs only.
    action_class: str | Opt = None


class RunNode(Model):
    id: str
    type: NodeType
    label: str
    actor: Actor | Literal["system"]
    status: NodeStatus
    version: str | Opt = None
    subtitle: str | Opt = None
    attempts: int | Opt = None
    duration_s: int | Opt = None
    cost: Money | Opt = None
    x: float
    y: float
    decision: DecisionRecord | Opt = None
    human_task_id: str | Opt = None
    tool_calls: list[ToolCall] | Opt = None
    output: str | Opt = None
    note: str | Opt = None


class RunEdge(Model):
    from_: str = Field(alias="from")  # "from" is a Python keyword
    to: str
    label: str | Opt = None
    taken: bool | Opt = None
    revision: bool | Opt = None


class TimelineEvent(Model):
    at: str
    actor: Actor
    who: str
    title: str
    detail: str | Opt = None
    node_id: str | Opt = None
    ref: str | Opt = None
    tone: Literal["default", "warn", "blocked", "ok"] | Opt = None


class Stages(Model):
    executed: StageState
    verified: StageState
    accepted: StageState
    settlement: StageState


class StageNotes(Model):
    executed: str | Opt = None
    verified: str | Opt = None
    accepted: str | Opt = None
    settlement: str | Opt = None


class Spent(Model):
    ai: Money
    human: Money
    tools: Money


class Attention(Model):
    tone: Literal["human", "blocked", "warn"]
    title: str
    body: str
    href: str | Opt = None
    cta: str | Opt = None


class EvidenceItem(Model):
    id: str
    label: str
    by: Actor
    who: str


class DeliverableRow(Model):
    label: str
    value: str


class DeliverableItem(Model):
    label: str
    detail: str


class Deliverable(Model):
    title: str
    kind: str
    summary: str
    rows: list[DeliverableRow]
    limitations: list[str]
    unresolved: list[str]
    evidence: list[EvidenceItem]
    # One entry per thing the run produced (such as an email draft), from the pack's deliverable view.
    items: list[DeliverableItem] | Opt = None


class RunSummary(Model):
    id: str
    pack_slug: str
    title: str
    status: RunStatus
    started_at: str
    ended_at: str | Opt = None
    started_by: str
    spent: Spent
    stages: Stages
    summary: str
    has_detail: bool = False
    # A test run started from the Studio ("Test in sandbox"): sandbox data, the pack need not be added.
    sandbox_test: bool | Opt = None


class Run(Model):
    id: str
    pack_slug: str
    title: str
    status: RunStatus
    started_at: str
    ended_at: str | Opt = None
    started_by: str
    input: str
    workflow_ref: str
    contract_ref: str
    budget: Money
    spent: Spent
    stages: Stages
    stage_notes: StageNotes | Opt = None
    summary: str
    # What the pinned pack promises (its `outcome`); real runs started after packs carried it.
    outcome: str | Opt = None
    nodes: list[RunNode]
    edges: list[RunEdge]
    timeline: list[TimelineEvent]
    attention: Attention | Opt = None
    deliverable: Deliverable | Opt = None
    recovered: str | Opt = None
    # A test run started from the Studio ("Test in sandbox"): sandbox data, the pack need not be added.
    sandbox_test: bool | Opt = None

    def summary_row(self) -> RunSummary:
        return RunSummary(
            id=self.id,
            pack_slug=self.pack_slug,
            title=self.title,
            status=self.status,
            started_at=self.started_at,
            ended_at=self.ended_at,
            started_by=self.started_by,
            spent=self.spent,
            stages=self.stages,
            summary=self.summary,
            has_detail=True,
            sandbox_test=self.sandbox_test,
        )


class PinnedVersion(Model):
    kind: str
    key: str
    version: int
    digest: str


class ReceiptItem(Model):
    seq: int
    at: str
    type: str
    node_id: str | Opt = None
    summary: str
    hash: str


class Receipt(Model):
    """A real run's hash-chained work receipt; `verified` is the chain recomputed now."""

    run_id: str
    verified: bool
    entries: int
    head_hash: str
    pinned: list[PinnedVersion]
    items: list[ReceiptItem]
