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


class DigestRow(Model):
    label: str
    value: str
    mono: bool | Opt = None


class EmailPreview(Model):
    subject: str
    to: str
    body: str


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
    preview: EmailPreview


class Earning(Model):
    task_id: str
    title: str
    at: str
    amount: Money
    verdict: ReviewVerdict
    status: Literal["OWED", "ELIGIBLE", "PAID_SIMULATED", "IN_REVIEW"]
