import re

from app import live_work, run_tasks, temporal_client, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.common import Money, money_text
from app.models.requests import SubmitReviewRequest
from app.models.work import Earning, HumanTask, OrderSide, PaymentSide, RedactedRecord
from app.routing import ApiRouter
from app.store import get_store, iso, locked_store

router = ApiRouter(prefix="/v1", tags=["reviewers"])

# Review verdict -> the workflow's human_result outcome. "Send back with corrections" resolves the task:
# the corrections travel as resolutions to the next step. Escalation has no route of its own, so it stops
# the run like a rejection.
OUTCOMES = {
    "APPROVED": "resolved",
    "REVISION_REQUIRED": "resolved",
    "REJECTED": "rejected",
    "ESCALATED": "rejected",
}
DONE_STATES = {"resolved": "SUBMITTED", "rejected": "SUBMITTED", "timeout": "EXPIRED"}
RUN_OUTCOMES = {"resolved": "CONTINUES", "rejected": "STOPS"}
MAX_TEXT = 1000  # characters of a note, record id or resolution sent to the workflow
MAX_RESOLUTIONS = 100
LEASE_MINUTES = 45
MINUTES_PER_RECORD = 5
OBLIGATIONS = [
    "Customer names are hidden. Do not try to find them.",
    "No copying, screenshots or downloads.",
]


# An agent's free-text note or flag may quote the customer. Reviewers see neither email addresses nor phone
# numbers: an email-like token, and a run of 9 to 15 digits written as a phone number (a lone ISO date, an
# amount or an order number does not qualify), read "Hidden".
EMAIL_LIKE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_LIKE = re.compile(r"(?<![\w#$.,/-])\+?\(?\d[\d\s().-]{7,}\d(?!\w)")
PHONE_DIGITS = range(9, 16)
HIDDEN = "Hidden"


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    return HIDDEN if sum(c.isdigit() for c in text) in PHONE_DIGITS else text


def _redacted(text: str) -> str:
    """`text` with email-like and phone-like tokens shown as "Hidden"."""
    return PHONE_LIKE.sub(_phone, EMAIL_LIKE.sub(HIDDEN, text))


def find_task(task_id: str) -> HumanTask:
    """A fixture task; never one in the live workspace."""
    task = None if workspace.live() else get_store().tasks.get(task_id)
    if task is None:
        raise ApiProblem(404, "NOT_FOUND", f"No task {task_id}.")
    return task


def _generic_record(item: dict) -> RedactedRecord:
    """A shared review item ({ref, date, amount_minor, currency, flag, note, counterpart_ref?}, the
    `shared/review-items` schema) as a reviewer record keyed by its `ref`."""
    ref = str(item["ref"])
    counterpart = str(item.get("counterpart_ref") or "None")
    amount = int(item.get("amount_minor") or 0)
    order = OrderSide(
        ref=ref,
        date=str(item.get("date") or ""),
        customer="Hidden",
        amount=money_text(amount, str(item.get("currency") or "USD")),
        payment_ref=counterpart,
    )
    payment = PaymentSide(ref=counterpart, date="", payer="Hidden", amount="", batch="")
    return RedactedRecord(
        id=ref,
        order=order,
        payment=payment,
        flag=_redacted(str(item.get("flag") or "Needs review")),
        agent_note=_redacted(str(item.get("note") or "")),
    )


def _record(item: dict, index: int) -> RedactedRecord:
    """One item a review task shows, as a reviewer record. The record id is what the reviewer's calls are
    keyed by. A shared review item has a `ref`; a reconciliation mismatch ({order_id, charge_id, kind, date,
    amount_minor, amount_diff_minor, currency, explanation}) keeps its own mapping."""
    if item.get("ref"):
        return _generic_record(item)
    order_id, charge_id = item.get("order_id"), item.get("charge_id")
    currency = str(item.get("currency") or "USD")
    day = str(item.get("date") or "")
    amount = int(item.get("amount_minor") or 0)
    paid = amount + int(item.get("amount_diff_minor") or 0) if order_id else amount
    order = OrderSide(
        ref=str(order_id or "No order"),
        date=day if order_id else "",
        customer="Hidden",
        amount=money_text(amount, currency) if order_id else "",
        payment_ref=str(charge_id or "None"),
    )
    payment = PaymentSide(
        ref=str(charge_id or "No payment"),
        date=day if charge_id else "",
        payer="Hidden",
        amount=money_text(paid, currency) if charge_id else "",
        batch="",
    )
    return RedactedRecord(
        id=str(order_id or charge_id or f"record-{index + 1}"),
        order=order,
        payment=payment,
        flag=str(item.get("kind") or "mismatch").replace("_", " ").capitalize(),
        agent_note=str(item.get("explanation") or ""),
    )


def _state(row: dict) -> str:
    if row["status"] in DONE_STATES:
        return DONE_STATES[row["status"]]
    return "CLAIMED" if (row["payload"] or {}).get("claimed_by") else "OFFERED"


def real_task(row: dict) -> HumanTask:
    """A run_tasks human row as the reviewer portal's HumanTask; records are the mismatches it shows."""
    payload = row["payload"] or {}
    shown = payload.get("show") if isinstance(payload.get("show"), list) else []
    records = [_record(item, i) for i, item in enumerate(shown) if isinstance(item, dict)]
    title = str(payload.get("title") or "Review the result")
    posted_at = iso(row["created_at"])
    return HumanTask(
        id=row["id"],
        version=1,
        run_id=row["run_id"],
        pack_name=row["run_title"] or "Workflow Pack",
        title=title,
        mode="CORRECTION",
        skill="Exception review",
        state=_state(row),
        pay=Money(amount_minor=0),
        pay_terms="Simulated pay: reviewer payouts are not live yet"
        if workspace.live()
        else "Demo run: no reviewer pay",
        est_minutes=max(MINUTES_PER_RECORD, MINUTES_PER_RECORD * len(records)),
        deadline=str(payload.get("expires_at") or posted_at),
        posted_at=posted_at,
        data_class="CONFIDENTIAL",
        regions=["US"],
        obligations=OBLIGATIONS,
        instructions=str(payload.get("instructions") or ""),
        question=title,
        records=records,
        lease_minutes=LEASE_MINUTES,
        buyer="A New Machines customer",
        real_run=True,
        run_outcome=RUN_OUTCOMES.get(row["status"]),
    )


@router.get("/human-tasks/eligible", operation_id="listEligibleHumanTasks", response_model=list[HumanTask])
def list_eligible_human_tasks(actor: CurrentActor) -> list[HumanTask]:
    # Offers show sanitized metadata only; records arrive with the task itself (API.md section 3).
    real = [real_task(row) for row in run_tasks.list_rows(actor.org_id, "human")]
    fixtures = [] if workspace.live() else list(get_store().tasks.values())
    offered = [t for t in real if t.state == "OFFERED"] + [t for t in fixtures if t.state == "OFFERED"]
    return [t.model_copy(update={"records": []}) for t in offered]


@router.get("/human-tasks/{task_id}", operation_id="getHumanTask", response_model=HumanTask)
def get_human_task(task_id: str, actor: CurrentActor) -> HumanTask:
    row = run_tasks.get_row(actor.org_id, "human", task_id)
    return real_task(row) if row is not None else find_task(task_id)


@router.get("/reviewer/earnings", operation_id="listEarnings", response_model=list[Earning])
def list_earnings(actor: CurrentActor) -> list[Earning]:
    """In the live workspace: the caller's decided tasks of the org's runs, simulated (no money moves)."""
    if workspace.live():
        return live_work.earnings(actor)
    return get_store().earnings


@router.post("/human-tasks/{task_id}:claim", operation_id="claimHumanTask", response_model=HumanTask)
def claim_human_task(task_id: str, actor: CurrentActor) -> HumanTask:
    if run_tasks.get_row(actor.org_id, "human", task_id) is not None:
        return real_task(run_tasks.claim(actor.org_id, task_id, actor.user_id))
    with locked_store():
        task = find_task(task_id)
        if task.state not in {"OFFERED", "EXPIRED", "CLAIMED"}:
            raise ApiProblem(409, "CONFLICT", "This task can no longer be claimed.")
        task.state = "CLAIMED"
        return task


def _submit_real(row: dict, body: SubmitReviewRequest, actor: Actor) -> HumanTask:
    """Record the review on the run task, then signal `human_result` to its workflow."""
    outcome = OUTCOMES[body.verdict]
    note = body.feedback_text[:MAX_TEXT]
    shown = {record.id for record in real_task(row).records}
    calls = [(rid, call) for rid, call in body.record_calls.items() if rid in shown][:MAX_RESOLUTIONS]
    resolutions = [
        {"order_id": record_id[:MAX_TEXT], "resolution": call[:MAX_TEXT], "note": ""}
        for record_id, call in calls
    ]
    result = {"outcome": outcome, "note": note, "resolutions": resolutions, "verdict": body.verdict}
    updated = run_tasks.decide(actor.org_id, "human", row["id"], outcome, actor.user_id, result)
    stored = updated["result"] or {}  # a repeated submit re-signals the decision first recorded
    run_tasks.signal(
        temporal_client.signal_human,
        row["run_id"],
        row["id"],
        updated["status"],
        stored.get("note", ""),
        stored.get("resolutions", []),
    )
    return real_task(updated)


@router.post("/human-tasks/{task_id}:submit", operation_id="submitHumanTask", response_model=HumanTask)
def submit_human_task(task_id: str, body: SubmitReviewRequest, actor: CurrentActor) -> HumanTask:
    row = run_tasks.get_row(actor.org_id, "human", task_id)
    if row is not None:
        return _submit_real(row, body, actor)
    with locked_store():
        task = find_task(task_id)
        if task.state != "CLAIMED":
            raise ApiProblem(409, "CONFLICT", "Claim the task before submitting a review.")
        task.state = "SUBMITTED"
        return task
