from typing import Literal

from app.models.common import Model, Money, Opt

ReviewVerdict = Literal["APPROVED", "REVISION_REQUIRED", "REJECTED", "ESCALATED"]
HumanTaskState = Literal["OFFERED", "CLAIMED", "SUBMITTED", "VALIDATING", "ACCEPTED", "EXPIRED", "CANCELLED"]
HumanMode = Literal[
    "APPROVAL", "EVALUATION", "NATURAL_FEEDBACK", "CORRECTION", "EXECUTION", "EXPERT_REVIEW", "QUALITY_AUDIT"
]


class OrderSide(Model):
    ref: str
    date: str
    customer: str
    amount: str
    payment_ref: str


class PaymentSide(Model):
    ref: str
    date: str
    payer: str
    amount: str
    batch: str


class RedactedRecord(Model):
    id: str
    order: OrderSide
    payment: PaymentSide
    flag: str
    agent_note: str


class HumanTask(Model):
    id: str
    version: int
    run_id: str
    pack_name: str
    title: str
    mode: HumanMode
    skill: str
    state: HumanTaskState
    pay: Money
    pay_terms: str
    est_minutes: int
    deadline: str
    posted_at: str
    data_class: Literal["INTERNAL", "CONFIDENTIAL"]
    regions: list[str]
    obligations: list[str]
    instructions: str
    question: str
    records: list[RedactedRecord]
    lease_minutes: int
    buyer: str
    # A task of a real run: the verdict goes straight to the run, with no acceptance check and no pay.
    real_run: bool | Opt = None
    # A submitted real-run task: whether the run goes on with the review or stops (reject or escalate).
    run_outcome: Literal["CONTINUES", "STOPS"] | Opt = None


class DigestRow(Model):
    label: str
    value: str
    mono: bool | Opt = None


class EmailPreview(Model):
    subject: str
    to: str
    body: str


class ApprovalAction(Model):
    """The step a real run asks to take once approved: the app it acts on, the workflow step, and the tool
    call. `mocked` is true when that call would run against sandbox data instead of the connected app."""

    app: str
    step: str
    tool: str | Opt = None  # "<connector>.<tool id>"
    operation: str | Opt = None  # the tool id in words, e.g. "append rows"
    summary: str | Opt = None
    mocked: bool


class Approval(Model):
    id: str
    run_id: str
    title: str
    requested_by: str
    requested_at: str
    expires_at: str
    status: Literal["PENDING", "GRANTED", "DECLINED", "EXPIRED"]
    policy_ref: str
    reason_codes: list[str]
    digest: list[DigestRow]
    preview: EmailPreview | Opt = None  # the email to send (fixture approvals)
    action: ApprovalAction | Opt = None  # the step to run (real-run approvals)
    summary: str | Opt = None  # what the step being approved will do (real runs)


class Earning(Model):
    task_id: str
    title: str
    at: str
    amount: Money
    verdict: ReviewVerdict
    status: Literal["OWED", "ELIGIBLE", "PAID_SIMULATED", "IN_REVIEW"]
    # Live workspace: no money moves yet, so every earning is simulated.
    simulated: bool | Opt = None
