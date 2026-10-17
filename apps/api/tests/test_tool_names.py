"""A connector tool is shown by its `name` where the connector file gives one, else by its id as words: in
the Studio's palette and in the run timeline's tool calls."""

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
