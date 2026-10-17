"""A connector tool is shown by its `name` where the connector file gives one, else by its id as words: in
the Studio's palette and in the run timeline's tool calls."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.defs.tool_names import action_name, id_words, tool_name
from app.worker.activities import _tool_event

EMAILS = {"id": "list_threads", "name": "List emails", "capability": "mail.read", "action_class": "read"}
THREADS = {"id": "list_threads_2", "name": "List threads", "capability": "mail.read", "action_class": "read"}
DRAFT = {"id": "create_draft", "capability": "mail.write", "action_class": "write"}
SNAPSHOT = {"defs": {"connector": {"gmail": {"body": {"app": "Gmail", "tools": [EMAILS, THREADS, DRAFT]}}}}}
PERMIT = SimpleNamespace(verdict="PERMIT", reason_codes=[], ref="policy")


def test_the_studio_name_is_the_name_else_the_id_as_a_sentence():
    assert tool_name(EMAILS) == "List emails"
    assert tool_name(THREADS) == "List threads"
    assert tool_name(DRAFT) == "Create draft"
    assert tool_name({"id": "append_rows", "name": "  "}) == "Append rows"


def test_the_timeline_action_is_the_name_else_the_id_as_words():
    assert id_words("append_rows") == "append rows"
    assert action_name(EMAILS, "list_threads") == "List emails"
    assert action_name(DRAFT, "create_draft") == "create draft"
    assert action_name(None, "list_threads_2") == "list threads 2"


def test_a_tool_call_event_carries_the_tools_name_and_falls_back_to_the_id():
    named = _tool_event(SNAPSHOT, "gmail.list_threads_2", "c1", PERMIT, None)
    assert (named["app"], named["action"]) == ("Gmail", "List threads")
    plain = _tool_event(SNAPSHOT, "gmail.create_draft", "c2", PERMIT, None)
    assert plain["action"] == "create draft"
    unknown = _tool_event(SNAPSHOT, "gmail.send_sms", "c3", PERMIT, None)
    assert (unknown["app"], unknown["action"]) == ("gmail", "send sms")  # the connector key, as before


def _approval_row(tool_ref: str, unlocked: list[dict] | None = None) -> dict:
    return {
        "id": "apr_1",
        "run_id": "run_1",
        "run_title": "Inbox triage",
        "node_id": "approve",
        "status": "pending",
        "decided_by": None,
        "created_at": datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
        "payload": {"tool_ref": tool_ref, "unlocked": unlocked or []},
        "connectors": SNAPSHOT["defs"]["connector"],
        "run_nodes": [
            {"id": "approve", "label": "Approve the drafts"},
            {"id": "send", "label": "Gmail: send"},
        ],
    }


def test_an_approval_names_its_step_as_the_timeline_does():
    from app.routers.approvals import real_approval

    named = real_approval(_approval_row("gmail.list_threads_2", [{"tool_ref": "gmail.list_threads"}]))
    assert named.action.operation == "List threads"
    assert named.action.unlocked[0].operation == "List emails"
    assert real_approval(_approval_row("gmail.create_draft")).action.operation == "create draft"
    assert real_approval(_approval_row("")).action.operation is None


def test_an_approval_names_its_steps_by_their_run_page_labels():
    from app.routers.approvals import POLICY_LINE, real_approval

    row = _approval_row("gmail.create_draft", [{"node": "send", "tool_ref": "gmail.create_draft"}])
    row["payload"]["target_node"] = "approve"
    approval = real_approval(row)
    assert approval.action.step == "Approve the drafts"
    assert approval.action.unlocked[0].step == "Gmail: send"
    assert {d.label: d.value for d in approval.digest}["Policy"] == POLICY_LINE
    # A node the projection does not know, or a row without one, keeps the id.
    row["payload"]["target_node"] = "other"
    assert real_approval(row).action.step == "other"
    assert real_approval({**row, "run_nodes": None}).action.step == "other"
