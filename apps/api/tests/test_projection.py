"""A run's result as the run page shows it: a pack's `deliverable_view`, its fallback, and the reconciliation
mapping that packs without a view keep."""

import copy
import logging
from functools import cache

import pytest

from app import settings
from app.defs.digest import digest
from app.defs.loader import load_bundle
from app.models.runs import Run
from app.runtime import projection

RECON = "order-payment-reconciliation"
REFUNDS = "refund-triage"
OVERDUE = "overdue-invoice-follow-up"


@cache
def _bundle():
    return load_bundle(settings.defs_dir())


def _snapshot(pack: str) -> dict:
    """A run snapshot that pins `pack` and every shared definition (enough for the projection)."""
    defs: dict = {}
    versions = []
    for (kind, key), d in sorted(_bundle().items.items()):
        if kind in ("pack", "workflow", "contract") and key != pack:
            continue
        defs.setdefault(kind, {})[key] = {"body": copy.deepcopy(d.body), "files": d.files}
        versions.append({"kind": kind, "key": key, "version": 1, "digest": digest(d)})
    return {"org_id": "org_demo", "versions": versions, "defs": defs, "overrides": {}, "disabled": []}


def _completed(pack: str, deliverable: dict, *, view: dict | None = None, mocked: bool = True) -> Run:
    snapshot = _snapshot(pack)
    if view is None:
        view = projection.deliverable_view(snapshot["defs"]["pack"])
    p = projection.initial_projection(
        "run_v", snapshot, {"since": "2026-10-06", "until": "2026-10-12"}, "You", 2500
    )
    event = {
        "seq": 9,
        "at": "2026-10-13T10:00:09.000000Z",
        "type": "run.completed",
        "node_id": "done",
        "data": {"deliverable": deliverable, "mocked": mocked},
    }
    return Run.model_validate(projection.apply_event(p, event, view))


def _drafts(n: int, body: str = "Hello,\n\nYour invoice is overdue.") -> dict:
    return {
        "drafts": [
            {
                "to": f"c{i}@example.com",
                "subject": f"Invoice INV-{i} is overdue",
                "body": body,
                "ref": f"INV-{i}",
            }
            for i in range(n)
        ]
    }


# --- step labels ------------------------------------------------------------------------------------


def _agent_step_label(agent_key: str, agent_body: dict | None) -> str:
    """The label of OVERDUE's first agent step when it runs `agent_key` (pinned with `agent_body`)."""
    snapshot = _snapshot(OVERDUE)
    workflow = next(iter(snapshot["defs"]["workflow"].values()))["body"]
    step = next(n for n in workflow["nodes"] if n["type"] == "agent")
    step["config"]["agent"] = agent_key
    if agent_body is not None:
        snapshot["defs"]["agent"][agent_key] = {"body": agent_body, "files": {}}
    p = projection.initial_projection("run_l", snapshot, {}, "You", 2500)
    return next(n["label"] for n in p["nodes"] if n["id"] == step["id"])


def test_a_workspace_agent_step_is_labelled_with_the_agents_name():
    key = "org-5c8192d7129c2fa2--invoice-helper"
    assert _agent_step_label(key, {"name": "Invoice helper", "runtime": {}}) == "Invoice helper"


def test_a_workspace_agent_step_never_carries_the_org_id():
    key = "org-5c8192d7129c2fa2--invoice-helper"
    for body in (None, {"runtime": {}}, {"name": "  ", "runtime": {}}):
        label = _agent_step_label(key, body)
        assert "5c8192d7129c2fa2" not in label and "org" not in label.lower(), label
        assert label == "Invoice helper"


def test_a_platform_agent_step_keeps_its_key_in_words():
    assert _agent_step_label("finance-agent", None) == "Finance agent"


# --- the view ---------------------------------------------------------------------------------------


def test_the_seed_packs_describe_their_deliverable_view():
    for pack in (REFUNDS, OVERDUE):
        view = projection.deliverable_view(_snapshot(pack)["defs"]["pack"])
        assert view is not None and view["kind"] == "Email drafts"
        assert [f["label"] for f in view["facts"]] == ["Drafts created"]
    assert projection.deliverable_view(_snapshot(RECON)["defs"]["pack"]) is None
    assert projection.deliverable_view(None) is None


def test_a_view_renders_kind_summary_facts_and_one_item_per_draft():
    long_body = "Hello, " + "x" * 300
    run = _completed(
        OVERDUE, _drafts(3) | {"drafts": [*_drafts(2)["drafts"], _drafts(1, long_body)["drafts"][0]]}
    )
    d = run.deliverable
    assert d.kind == "Email drafts" and d.title == run.title
    assert d.summary == "3 reminder emails were drafted on sandbox data. No email was created in Gmail."
    assert run.summary == d.summary
    assert [(r.label, r.value) for r in d.rows] == [("Drafts created", "3")]
    assert [i.label for i in d.items] == [
        "c0@example.com — Invoice INV-0 is overdue",
        "c1@example.com — Invoice INV-1 is overdue",
        "c0@example.com — Invoice INV-0 is overdue",
    ]
    assert d.items[0].detail == "Hello,\n\nYour invoice is overdue."
    assert d.items[2].detail == long_body[:160] and len(d.items[2].detail) == 160
    assert d.limitations == [projection.SIMULATED_LIMITATION] and d.unresolved == [] and d.evidence == []


def test_a_view_summary_counts_one_draft_in_the_singular():
    assert _completed(OVERDUE, _drafts(1), mocked=False).deliverable.summary == (
        "1 reminder email was drafted, ready for you to check and send."
    )
    assert _completed(REFUNDS, _drafts(1), mocked=False).deliverable.summary == (
        "1 refund reply was drafted, ready for you to check and send. No refund has been issued."
    )
    assert _completed(REFUNDS, _drafts(2), mocked=False).deliverable.summary.startswith(
        "2 refund replies were drafted, ready"
    )


def test_a_sandbox_run_says_its_drafts_were_made_on_sandbox_data():
    assert _completed(OVERDUE, _drafts(4)).deliverable.summary == (
        "4 reminder emails were drafted on sandbox data. No email was created in Gmail."
    )
    assert _completed(OVERDUE, _drafts(1)).deliverable.summary == (
        "1 reminder email was drafted on sandbox data. No email was created in Gmail."
    )
    assert _completed(REFUNDS, _drafts(2)).deliverable.summary == (
        "2 refund replies were drafted on sandbox data. No email was created in Gmail and no refund has "
        "been issued."
    )
    assert _completed(REFUNDS, _drafts(1)).deliverable.summary == (
        "1 refund reply was drafted on sandbox data. No email was created in Gmail and no refund has been "
        "issued."
    )


def test_a_run_with_a_sandbox_tool_call_is_mocked_even_if_the_completion_does_not_say_so():
    call = {
        "id": "tc_1",
        "tool_ref": "gmail.create_draft",
        "policy": {"verdict": "PERMIT", "reason_codes": []},
        "ok": True,
        "mocked": True,
    }
    run = _fold(
        OVERDUE,
        ("tool.call", "send", call),
        ("run.completed", "done", {"deliverable": _drafts(2), "mocked": False}),
    )
    assert run.deliverable.summary.endswith("on sandbox data. No email was created in Gmail.")
    assert run.deliverable.limitations == [projection.SIMULATED_LIMITATION]
    live = _fold(
        OVERDUE,
        ("tool.call", "send", {**call, "mocked": False}),
        ("run.completed", "done", {"deliverable": _drafts(2), "mocked": False}),
    )
    assert live.deliverable.summary == "2 reminder emails were drafted, ready for you to check and send."
    assert live.deliverable.limitations == []


def test_any_error_in_a_view_falls_back_and_never_fails_the_fold(monkeypatch):
    def boom(*_args, **_kw):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(projection.cel, "evaluate", boom)
    run = _completed(OVERDUE, {"summary": "Own summary.", "drafts": []})
    assert run.status == "COMPLETED" and run.deliverable.summary == "Own summary."
    assert run.deliverable.rows == [] and run.deliverable.items is None


def test_a_run_carries_its_pinned_pack_outcome_and_tool_action_classes():
    snapshot = _snapshot(REFUNDS)
    p = projection.initial_projection(
        "run_v", snapshot, {"since": "2026-10-06", "until": "2026-10-12"}, "You", 2500
    )
    data = {
        "id": "tc_1",
        "tool_ref": "gmail.create_draft",
        "app": "Gmail",
        "action": "create draft",
        "capability": "mail.write",
        "action_class": "write",
        "policy": {"verdict": "PERMIT", "reason_codes": ["APPROVAL_GRANTED"]},
        "ok": True,
        "mocked": True,
    }
    event = {"seq": 1, "at": "2026-10-13T10:00:01Z", "type": "tool.call", "node_id": "send", "data": data}
    run = Run.model_validate(projection.apply_event(p, event))
    assert run.outcome == snapshot["defs"]["pack"][REFUNDS]["body"]["outcome"]
    [call] = next(n for n in run.nodes if n.id == "send").tool_calls
    assert call.action_class == "write"
    older = {**data}
    older.pop("action_class")
    run = Run.model_validate(projection.apply_event(p, {**event, "data": older}))
    assert next(n for n in run.nodes if n.id == "send").tool_calls[0].action_class is None


def _fold(pack: str, *events: tuple[str, str | None, dict]) -> Run:
    p = projection.initial_projection("run_v", _snapshot(pack), {"as_of": "2026-10-13"}, "You", 2500)
    for seq, (type_, node, data) in enumerate(events, 1):
        event = {
            "seq": seq,
            "at": f"2026-10-13T10:00:{seq:02d}Z",
            "type": type_,
            "node_id": node,
            "data": data,
        }
        p = projection.apply_event(p, event, projection.deliverable_view(_snapshot(pack)["defs"]["pack"]))
    return Run.model_validate(p)


def test_a_run_that_ends_without_a_verification_node_was_not_verified():
    plan = {"summary": "Checked 9 invoices: none is overdue.", "messages": [], "review_items": []}
    run = _fold(
        OVERDUE,
        ("node.completed", "check", {"route": "nothing"}),
        ("run.completed", "nothing", {"deliverable": plan}),
    )
    assert run.status == "COMPLETED" and run.stages.verified == "not_required"
    assert run.stages.executed == "done" and run.deliverable.summary == plan["summary"]


def test_a_run_whose_verification_passed_is_verified():
    run = _fold(
        OVERDUE,
        ("node.completed", "verify", {"route": "pass"}),
        ("run.completed", "done", {"deliverable": _drafts(1)}),
    )
    assert run.stages.verified == "done"


def test_a_view_shows_at_most_fifty_items():
    run = _completed(REFUNDS, _drafts(60))
    assert len(run.deliverable.items) == 50
    assert run.deliverable.rows[0].value == "60"
    assert "no refund has been issued" in run.deliverable.summary


def test_a_view_over_a_run_that_ended_without_drafts_shows_its_own_summary():
    plan = {
        "summary": "Checked 9 invoices as of 2026-08-01: none is overdue.",
        "messages": [],
        "review_items": [],
    }
    run = _completed(OVERDUE, plan, mocked=False)
    d = run.deliverable
    assert d.summary == plan["summary"] and run.summary == plan["summary"]
    assert [(r.label, r.value) for r in d.rows] == [("Drafts created", "0")]
    assert d.items == [] and d.limitations == []


def test_a_cel_error_in_the_view_falls_back_to_the_summary_only(caplog):
    view = {
        "kind": "Email drafts",
        "summary": "='Saved ' + string(size(deliverable.drafts)) + ' drafts.'",
        "facts": [{"label": "Drafts created", "value": "=size(deliverable.nope)"}],
        "items": {"from": "=deliverable.drafts", "label": "=item.to", "detail": "=item.body"},
    }
    with caplog.at_level(logging.WARNING, logger="app.runtime.projection"):
        run = _completed(OVERDUE, _drafts(2), view=view)
    d = run.deliverable
    assert run.status == "COMPLETED"
    # The summary evaluated, so it stays; the facts and items are dropped together.
    assert d.kind == "Email drafts" and d.summary == "Saved 2 drafts." and d.rows == [] and d.items is None
    assert run.summary == "Saved 2 drafts."
    assert any("deliverable view did not evaluate" in r.getMessage() for r in caplog.records)


def test_a_failing_view_summary_keeps_the_deliverable_own_summary():
    view = {"kind": "Plan", "summary": "=deliverable.missing", "facts": []}
    run = _completed(OVERDUE, {"summary": "Checked 9 invoices.", "messages": []}, view=view)
    assert run.deliverable.summary == "Checked 9 invoices." and run.deliverable.rows == []


@pytest.mark.parametrize(
    "items",
    [
        {"from": "=deliverable.drafts[0]", "label": "=item.to", "detail": "=item.body"},  # not a list
        {"from": "=deliverable.drafts", "label": "=item.missing", "detail": "=item.body"},
    ],
)
def test_bad_view_items_fall_back_too(items):
    view = {
        "kind": "Email drafts",
        "summary": "Done.",
        "facts": [{"label": "A", "value": "1"}],
        "items": items,
    }
    d = _completed(OVERDUE, _drafts(1), view=view).deliverable
    assert d.summary == "Done." and d.rows == [] and d.items is None


def test_view_literals_are_shown_as_written():
    view = {"kind": "Notes", "summary": "All done.", "facts": [{"label": "Mode", "value": "sandbox"}]}
    d = _completed(OVERDUE, {"anything": 1}, view=view).deliverable
    assert (d.kind, d.summary, [(r.label, r.value) for r in d.rows], d.items) == (
        "Notes",
        "All done.",
        [("Mode", "sandbox")],
        None,
    )


# --- packs without a view keep the reconciliation mapping -------------------------------------------------

REPORT = {
    "summary": "Checked 12 orders.",
    "rows": [
        ["2026-10-06", "#1001", "matched", "45.00", "matched", ""],
        ["2026-10-07", "#1002", "mismatch", "129.00", "open", "Short by the fee"],
        ["short row"],
    ],
    "totals": {
        "orders_count": 12,
        "matched_count": 10,
        "mismatch_count": 2,
        "net_difference_minor": -7040,
        "currency": "USD",
    },
}


def test_a_pack_without_a_view_keeps_the_reconciliation_mapping():
    run = _completed(RECON, REPORT)
    assert run.deliverable.model_dump(by_alias=True, exclude_none=True) == {
        "title": run.title,
        "kind": "Report rows",
        "summary": "Checked 12 orders.",
        "rows": [
            {"label": "Orders checked", "value": "12"},
            {"label": "Matched", "value": "10"},
            {"label": "Mismatches", "value": "2"},
            {"label": "Net difference", "value": "-70.40 USD"},
            {"label": "Rows in the report", "value": "2"},
        ],
        "limitations": [projection.SIMULATED_LIMITATION],
        "unresolved": ["#1002: Short by the fee"],
        "evidence": [],
    }
    assert run.summary == "Checked 12 orders."


def test_folding_without_a_view_is_unchanged_for_any_pack():
    """Runs pinned before packs had views fold without one, exactly as before."""
    snapshot = _snapshot(RECON)
    p = projection.initial_projection(
        "run_v", snapshot, {"since": "2026-10-06", "until": "2026-10-12"}, "You", 2500
    )
    event = {"seq": 1, "at": "2026-10-13T10:00:01Z", "type": "run.completed", "node_id": "done", "data": {}}
    assert projection.apply_event(p, event) == projection.apply_event(p, event, None)
    done = projection.apply_event(p, event)
    assert done["summary"] == "Completed." and "deliverable" not in done


# --- a review step on the timeline ------------------------------------------------------------------


def _reviewed(events: list[tuple[str, str, dict]]) -> dict:
    """The reconciliation pack's run with `events` ((type, node id, data), in order) folded in, as the
    projection dict (`_fold` gives the validated Run; these tests read the timeline's wire form)."""
    p = projection.initial_projection(
        "run_v", _snapshot(RECON), {"since": "2026-10-06", "until": "2026-10-12"}, "You", 2500
    )
    for seq, (type_, node_id, data) in enumerate(events, start=1):
        at = f"2026-10-13T10:00:{seq:02d}Z"
        p = projection.apply_event(p, {"seq": seq, "at": at, "type": type_, "node_id": node_id, "data": data})
    Run.model_validate(p)  # still a valid Run
    return p


def _review(p: dict) -> dict:
    return next(n for n in p["nodes"] if n["id"] == "review")


def _review_lines(p: dict) -> list[dict]:
    return [t for t in p["timeline"] if t.get("nodeId") == "review"]


OPENED = ("human.task", "review", {"task_id": "ht_1", "status": "open", "title": "Resolve mismatches"})


def test_a_rejected_review_is_one_line_with_the_reviewer_s_note():
    """The reviewer's decision line (`human.task`) carries the note; the step's `node.failed` that follows
    adds no second line with the same note, as the completed path adds none. The step itself still fails."""
    note = "Wrong period: these are September orders."
    rejected = {"task_id": "ht_1", "status": "rejected", "decided_by": "Ana Reyes", "note": note}
    p = _reviewed(
        [
            ("node.started", "review", {}),
            ("node.waiting", "review", {"note": "Resolve mismatches"}),
            OPENED,
            ("human.task", "review", rejected),
            ("node.failed", "review", {"status": "REJECTED", "route": "rejected", "error": note}),
        ]
    )
    assert [(t["who"], t["title"], t.get("detail")) for t in _review_lines(p)] == [
        ("Human workforce", "Created task ht_1", "Resolve mismatches"),
        ("Ana Reyes", "Rejected the task", note),
    ]
    assert [t for t in p["timeline"] if note in str(t)] == [_review_lines(p)[1]]
    assert _review(p)["status"] == "REJECTED" and _review(p)["note"] == note
    assert [e["taken"] for e in p["edges"] if e["from"] == "review"] == [False, True, False]
    assert p["status"] == "RUNNING"


def test_a_review_that_timed_out_says_so_once():
    p = _reviewed(
        [
            ("node.started", "review", {}),
            OPENED,
            ("human.task", "review", {"task_id": "ht_1", "status": "timeout"}),
            (
                "node.failed",
                "review",
                {"status": "TIMED_OUT", "route": "timeout", "error": "The task ended: timeout."},
            ),
        ]
    )
    assert [(t["actor"], t["title"]) for t in _review_lines(p)] == [
        ("system", "Created task ht_1"),
        ("system", "The task timed out"),
    ]
    assert _review(p)["status"] == "TIMED_OUT"


def test_a_review_that_failed_without_a_decision_still_says_why():
    """A guard or an activity error fails the step with no decision to show (`PackActivities.fail`): the
    buyer still reads why it stopped. The same for a step that failed before any task was opened."""
    reason = "BUDGET_EXCEEDED: the run's budget is spent"
    opened = [("node.started", "review", {}), OPENED]
    for events in (opened, opened[:1]):
        p = _reviewed([*events, ("node.failed", "review", {"error": reason})])
        last = _review_lines(p)[-1]
        label = _review(p)["label"]
        assert (last["title"], last["detail"], last["tone"]) == (f"{label} did not finish", reason, "blocked")
        assert _review(p)["status"] == "FAILED"


def test_a_revisited_review_that_fails_before_its_task_opens_still_says_why():
    """The first task resolved; the step is revisited and fails with no new task (`PackActivities.fail`, no
    status): the first task's decision does not cover it, so the step's line appears."""
    p = _reviewed(
        [
            ("node.started", "review", {}),
            OPENED,
            ("human.task", "review", {"task_id": "ht_1", "status": "resolved", "note": "Fine."}),
            ("node.completed", "review", {"route": "resolved", "summary": "Fine."}),
            ("node.started", "review", {}),
            ("node.failed", "review", {"error": "ACTIVITY_FAILED: open_task"}),
        ]
    )
    assert [t["title"] for t in _review_lines(p)] == [
        "Created task ht_1",
        "Resolved the task",
        f"{_review(p)['label']} did not finish",
    ]
    assert _review(p)["status"] == "FAILED" and _review(p)["note"] == "ACTIVITY_FAILED: open_task"


def test_a_retried_review_s_second_task_has_its_own_lines():
    """A second attempt opens a new task: the first task's decision line does not stand for the second."""
    p = _reviewed(
        [
            ("node.started", "review", {}),
            OPENED,
            ("human.task", "review", {"task_id": "ht_1", "status": "rejected", "note": "No."}),
            ("node.failed", "review", {"status": "REJECTED", "route": "rejected", "error": "No."}),
            ("node.started", "review", {}),
            ("human.task", "review", {"task_id": "ht_2", "status": "open", "title": "Resolve mismatches"}),
            ("node.failed", "review", {"error": "ATTEMPTS_EXCEEDED: more than 4 node executions"}),
        ]
    )
    assert [t["title"] for t in _review_lines(p)] == [
        "Created task ht_1",
        "Rejected the task",
        "Created task ht_2",
        f"{_review(p)['label']} did not finish",
    ]


# --- why a run stopped -----------------------------------------------------------------------------------

APPROVAL_ASKED = (
    "approval",
    "approve",
    {"approval_id": "apr_1", "status": "pending", "title": "Save drafts"},
)


def _stopped_after(decision: str, failed: dict) -> Run:
    """The overdue pack's run whose approval ended with `decision`, then failed at its `failed` end."""
    return _fold(
        OVERDUE,
        ("node.started", "approve", {}),
        APPROVAL_ASKED,
        ("approval", "approve", {"approval_id": "apr_1", "status": decision, "decided_by": "Ana Reyes"}),
        ("node.failed", "approve", failed),
        ("node.started", "failed", {}),
        ("node.completed", "failed", {}),
        ("run.failed", "failed", {"reason": "The approval was declined."}),
    )


def test_a_run_stopped_by_a_declined_approval_says_declined():
    run = _stopped_after("denied", {"status": "REJECTED", "route": "denied", "error": "No."})
    assert run.status == "FAILED" and run.stop_reason == "declined"
    assert run.summary_row().stop_reason == "declined"
    assert run.model_dump(by_alias=True)["stopReason"] == "declined"


def test_a_run_whose_approval_timed_out_or_that_failed_elsewhere_is_not_declined():
    timed_out = _stopped_after("timeout", {"status": "TIMED_OUT", "route": "timeout", "error": "Too late."})
    assert timed_out.status == "FAILED" and timed_out.stop_reason is None
    failed = _fold(OVERDUE, ("run.failed", None, {"reason": "ACTIVITY_FAILED: plan"}))
    assert failed.stop_reason is None and failed.summary_row().stop_reason is None


def test_an_agent_step_names_its_model_profile_in_sentence_case():
    run = _fold(OVERDUE)
    subtitles = {n.id: n.subtitle for n in run.nodes if n.type == "agent"}
    assert subtitles == {"plan": "Reasoning model", "draft": "Fast model"}
