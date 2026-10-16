import json
from collections.abc import Callable

from app import live_work, network_reviewers, review_routing, run_tasks, temporal_client, workspace
from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.common import Model, Money, money_text
from app.models.requests import SubmitReviewRequest
from app.models.work import DigestRow, Earning, HumanTask, OrderSide, PaymentSide, RedactedRecord
from app.models.workforce import NetworkProfile, NetworkProfileRequest
from app.redaction import redacted, scrub, without_name
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
MAX_DETAILS = 30  # rows a review's details show at most
MAX_DETAIL_CHARS = 2000  # characters of one detail row's value
MAX_LABEL_CHARS = 80  # characters of one detail row's label
OBLIGATIONS = [
    "Customer names are hidden. Do not try to find them.",
    "No copying, screenshots or downloads.",
]
TEAM_PAY_TERMS = "Team review: unpaid"
NETWORK_PAY_TERMS = "Simulated pay: no money moves"
DEMO_PAY_TERMS = "Demo run: no reviewer pay"


def find_task(task_id: str) -> HumanTask:
    """A fixture task; never one in the live workspace."""
    task = None if workspace.live() else get_store().tasks.get(task_id)
    if task is None:
        raise ApiProblem(404, "NOT_FOUND", f"No task {task_id}.")
    return task


def _generic_record(item: dict) -> RedactedRecord:
    """A shared review item ({ref, date, amount_minor, currency, flag, note, counterpart_ref?}, the
    `shared/review-items` schema) as a reviewer record keyed by its `ref`. An item with no amount (a support
    email) or no counterpart leaves that text empty. A support email's ref may be the sender's address, so
    the refs show with contact details hidden, like the notes (`_indexed_records` renames such an id)."""
    ref = redacted(str(item["ref"]))
    counterpart = redacted(str(item.get("counterpart_ref") or ""))
    amount = int(item.get("amount_minor") or 0)
    order = OrderSide(
        ref=ref,
        date=str(item.get("date") or ""),
        customer="Hidden",
        amount=money_text(amount, str(item.get("currency") or "USD")) if amount else "",
        payment_ref=counterpart,
    )
    payment = PaymentSide(ref=counterpart, date="", payer="Hidden", amount="", batch="")
    return RedactedRecord(
        id=str(item["ref"]),
        order=order,
        payment=payment,
        flag=redacted(str(item.get("flag") or "Needs review")),
        agent_note=redacted(str(item.get("note") or "")),
        kind="item",
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
        kind="reconciliation",
    )


def _state(row: dict) -> str:
    if row["status"] in DONE_STATES:
        return DONE_STATES[row["status"]]
    return "CLAIMED" if (row["payload"] or {}).get("claimed_by") else "OFFERED"


def _shown_items(payload: dict) -> list[tuple[int, dict]]:
    """The items a task shows that are records, each with its position in `show`."""
    shown = payload.get("show") if isinstance(payload.get("show"), list) else []
    return [(i, item) for i, item in enumerate(shown) if isinstance(item, dict)]


def _renamed(
    indexed: list[tuple[int, RedactedRecord]], renames: Callable[[str], bool]
) -> list[tuple[int, RedactedRecord]]:
    """`indexed` with each id `renames` picks replaced by `record-<position in show>`, made unique against
    every other shown id. `_shown_ids` maps a renamed id back."""
    picked = {i for i, record in indexed if renames(record.id)}
    taken = {record.id for i, record in indexed if i not in picked}
    out = []
    for i, record in indexed:
        if i in picked:
            record_id = _free_id(f"record-{i + 1}", taken)
            taken.add(record_id)
            record = record.model_copy(update={"id": record_id})
        out.append((i, record))
    return out


def _indexed_records(payload: dict) -> list[tuple[int, RedactedRecord]]:
    """The records a task shows, as the org's own reviewers see them, each with its position in `show`. An id
    with contact details in it (an item whose ref is an email address) is renamed (`_renamed`)."""
    indexed = [(i, _record(item, i)) for i, item in _shown_items(payload)]
    return _renamed(indexed, lambda record_id: redacted(record_id) != record_id)


def _records(payload: dict) -> list[RedactedRecord]:
    return [record for _, record in _indexed_records(payload)]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _label(key: str) -> str:
    """A shown object's key as a row label: `request_id` reads "Request id"."""
    words = key.replace("_", " ").replace("-", " ").strip()
    return _clip(words[:1].upper() + words[1:], MAX_LABEL_CHARS) if words else "Details"


def _details(show: object, clean: Callable[[str], str]) -> list[DigestRow]:
    """What a review shows that is not a list of records, as labelled rows. A pack built in the Studio often
    shows an agent's output, an object: one row per key, and a last row saying how many more there are. A
    list of objects shows as records instead (none here); a text, a number or a list of values is one row,
    as are the plain values beside the objects in one list (one value shows as itself, nulls are dropped).

    Each text is cleaned by `clean` whole, before it is shaped or cut, so a name or an email address is
    never cut to a part the cleaning no longer recognises."""
    if isinstance(show, list) and any(isinstance(item, dict) for item in show):
        plain = [item for item in show if not isinstance(item, dict) and item is not None]
        show = plain[0] if len(plain) == 1 else plain  # the objects are the records
    if show is None or show in ("", [], {}):
        return []
    rows = list(show.items()) if isinstance(show, dict) else [("Details", show)]
    out = [
        DigestRow(label=_label(clean(str(key))), value=_clip(clean(_as_text(value)), MAX_DETAIL_CHARS))
        for key, value in rows[:MAX_DETAILS]
    ]
    if len(rows) > MAX_DETAILS:
        out.append(
            DigestRow(label="More", value=f"{len(rows) - MAX_DETAILS} more fields are not shown here.")
        )
    return out


def _pay(payload: dict, via: str | None) -> tuple[int, str]:
    """(pay in minor units, pay terms) of the task as this reviewer sees it. A network copy shows the pay its
    network claim recorded, or before a claim the pay such a claim would record."""
    if via == "network":
        claimed = live_work.pay_minor(payload) if payload.get("claimed_via") == "network" else 0
        return claimed or review_routing.network_pay_minor(payload), NETWORK_PAY_TERMS
    if via == "team":
        return 0, TEAM_PAY_TERMS
    return 0, DEMO_PAY_TERMS


def _unnamed[M: Model](side: M, org_name: str | None) -> M:
    """`side` with the org's name read as "the customer" in each of its texts."""
    texts = {k: without_name(v, org_name) for k, v in side.model_dump().items() if isinstance(v, str)}
    return side.model_copy(update=texts)


def _free_id(base: str, taken: set[str]) -> str:
    """`base`, or `base-2`, `base-3`... : the first that no other shown record has."""
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _network_records(payload: dict, org_name: str | None) -> list[RedactedRecord]:
    """The records as a network reviewer sees them (`_network_record`). An id that names the org is renamed
    too (`_renamed`)."""
    indexed = _renamed(
        _indexed_records(payload), lambda record_id: without_name(record_id, org_name) != record_id
    )
    return [_network_record(record, org_name) for _, record in indexed]


def _network_record(record: RedactedRecord, org_name: str | None) -> RedactedRecord:
    """A record as a network reviewer sees it: the org's name and contact details scrubbed from its notes, and
    the org's name from its references."""
    return record.model_copy(
        update={
            "order": _unnamed(record.order, org_name),
            "payment": _unnamed(record.payment, org_name),
            "flag": scrub(record.flag, org_name),
            "agent_note": scrub(record.agent_note, org_name),
        }
    )


def real_task(row: dict) -> HumanTask:
    """A run_tasks human row as the reviewer portal's HumanTask; records are the items it shows. A live row's
    `via` decides the copy: "team" is the org's own, unpaid; "network" has the org's name and contact details
    scrubbed from every text and simulated pay. A demo row (no `via`) is the org's own copy, unpaid."""
    payload = row["payload"] or {}
    via = row.get("via")
    network = via == "network"
    org_name = row.get("org_name")

    def text(value: str) -> str:
        return scrub(value, org_name) if network else value

    records = _network_records(payload, org_name) if network else _records(payload)
    details = _details(payload.get("show"), (lambda v: scrub(v, org_name)) if network else redacted)
    title = text(str(payload.get("title") or "Review the result"))
    pay, terms = _pay(payload, via)
    posted_at = iso(row["created_at"])
    deadline = str(payload.get("expires_at") or posted_at)
    # Another org's run is not the network reviewer's to know: the copy has no run id, and its task id is the
    # task's public id (`review_routing.address`), since the task's own id is built from the run id.
    return HumanTask(
        id=review_routing.address(row),
        version=1,
        run_id="" if network else row["run_id"],
        pack_name=text(row["run_title"] or "Workflow Pack"),
        title=title,
        mode="CORRECTION",
        skill="Exception review",
        state=_state(row),
        pay=Money(amount_minor=pay),
        pay_terms=terms,
        est_minutes=max(MINUTES_PER_RECORD, MINUTES_PER_RECORD * len(records)),
        deadline=without_name(deadline, org_name) if network else deadline,
        posted_at=posted_at,
        data_class="CONFIDENTIAL",
        regions=["US"],
        obligations=OBLIGATIONS,
        instructions=text(str(payload.get("instructions") or "")),
        question=title,
        records=records,
        lease_minutes=LEASE_MINUTES,
        buyer="A New Machines customer",
        real_run=True,
        run_outcome=RUN_OUTCOMES.get(row["status"]),
        via=via,
        details=details or None,
    )


def id_map(shown_ids: list[str], real_ids: list[str]) -> dict[str, str]:
    """Shown record id -> real record id, position by position. A shown id that stands for two different
    real ids is left out, so a call on it is dropped rather than sent to the wrong record."""
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for shown, real in zip(shown_ids, real_ids, strict=True):
        if mapping.setdefault(shown, real) != real:
            ambiguous.add(shown)
    return {shown: real for shown, real in mapping.items() if shown not in ambiguous}


def _shown_ids(row: dict) -> dict[str, str]:
    """The record ids the reviewer was shown -> the records' real ids (they differ where an id was renamed:
    one with contact details in it, or in a network copy one that names the org)."""
    real = [_record(item, i).id for i, item in _shown_items(row["payload"] or {})]
    return id_map([record.id for record in real_task(row).records], real)


def _offered_rows(actor: Actor) -> list[dict]:
    """Rows to list as offers: in the live workspace only open, unclaimed tasks are read, so the list's limit
    counts offers alone."""
    if workspace.live():
        return review_routing.visible_rows(actor.org_id, actor.user_id, offered=True)
    return run_tasks.list_rows(actor.org_id, "human")


def _human_row(actor: Actor, task_id: str) -> dict | None:
    """The task as the actor may see it: by the routing rules in the live workspace, else the org's own."""
    if workspace.live():
        return review_routing.visible_row(actor.org_id, actor.user_id, task_id)
    return run_tasks.get_row(actor.org_id, "human", task_id)


@router.get("/human-tasks/eligible", operation_id="listEligibleHumanTasks", response_model=list[HumanTask])
def list_eligible_human_tasks(actor: CurrentActor) -> list[HumanTask]:
    # Offers show sanitized metadata only; records arrive with the task itself (API.md section 3).
    real = [real_task(row) for row in _offered_rows(actor)]
    fixtures = [] if workspace.live() else list(get_store().tasks.values())
    offered = [t for t in real if t.state == "OFFERED"] + [t for t in fixtures if t.state == "OFFERED"]
    return [t.model_copy(update={"records": [], "details": None}) for t in offered]


@router.get("/human-tasks/{task_id}", operation_id="getHumanTask", response_model=HumanTask)
def get_human_task(task_id: str, actor: CurrentActor) -> HumanTask:
    row = _human_row(actor, task_id)
    return real_task(row) if row is not None else find_task(task_id)


@router.get("/reviewer/earnings", operation_id="listEarnings", response_model=list[Earning])
def list_earnings(actor: CurrentActor) -> list[Earning]:
    """In the live workspace: the caller's decided tasks of the org's runs and the network reviews they did
    for other orgs, simulated (no money moves)."""
    if workspace.live():
        return live_work.earnings(actor)
    return get_store().earnings


NETWORK_LIVE_ONLY = "The reviewer network is part of the live workspace."


def _network_live() -> None:
    if not workspace.live():
        raise ApiProblem(404, "NOT_FOUND", NETWORK_LIVE_ONLY)


@router.get("/reviewer/profile", operation_id="getReviewerProfile", response_model=NetworkProfile)
def get_reviewer_profile(actor: CurrentActor) -> NetworkProfile:
    """The signed-in user's profile as a New Machines network reviewer; not enabled until they turn it on.
    Live workspace only (404 in the demo)."""
    _network_live()
    return network_reviewers.profile(actor)


@router.put("/reviewer/profile", operation_id="updateReviewerProfile", response_model=NetworkProfile)
def update_reviewer_profile(body: NetworkProfileRequest, actor: CurrentActor) -> NetworkProfile:
    """Turn "Review for the network" on or off and save the profile (name, languages, skills). Turning it off
    returns the open tasks the user claimed through the network to the queue. Live workspace only."""
    _network_live()
    return network_reviewers.update(actor, body)


@router.post("/human-tasks/{task_id}:claim", operation_id="claimHumanTask", response_model=HumanTask)
def claim_human_task(task_id: str, actor: CurrentActor) -> HumanTask:
    if _human_row(actor, task_id) is not None:
        if workspace.live():
            return real_task(review_routing.claim(actor.org_id, actor.user_id, task_id))
        return real_task(run_tasks.claim(actor.org_id, task_id, actor.user_id))
    with locked_store():
        task = find_task(task_id)
        if task.state not in {"OFFERED", "EXPIRED", "CLAIMED"}:
            raise ApiProblem(409, "CONFLICT", "This task can no longer be claimed.")
        task.state = "CLAIMED"
        return task


def _submit_real(row: dict, body: SubmitReviewRequest, actor: Actor) -> HumanTask:
    """Record the review on the run task, then signal `human_result` to its workflow. Item notes follow the
    general note, each under the item's real id, so a renamed id never reaches the run."""
    outcome = OUTCOMES[body.verdict]
    shown = _shown_ids(row)
    item_notes = [
        f"{real}: {text}"
        for shown_id, real in shown.items()
        if (text := body.record_notes.get(shown_id, "").strip())
    ]
    note = "\n\n".join([body.feedback_text, *item_notes])[:MAX_TEXT]
    calls = [(shown[rid], call) for rid, call in body.record_calls.items() if rid in shown][:MAX_RESOLUTIONS]
    resolutions = [
        {"order_id": record_id[:MAX_TEXT], "resolution": call[:MAX_TEXT], "note": ""}
        for record_id, call in calls
    ]
    result = {"outcome": outcome, "note": note, "resolutions": resolutions, "verdict": body.verdict}
    if workspace.live():
        updated = review_routing.decide(
            actor.org_id, actor.user_id, review_routing.address(row), outcome, result
        )
    else:
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
    row = _human_row(actor, task_id)
    if row is not None:
        return _submit_real(row, body, actor)
    with locked_store():
        task = find_task(task_id)
        if task.state != "CLAIMED":
            raise ApiProblem(409, "CONFLICT", "Claim the task before submitting a review.")
        task.state = "SUBMITTED"
        return task
