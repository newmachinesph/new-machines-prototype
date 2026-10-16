"""Sub-project C, part 5: a pack draft becomes the seed pack shapes and back, and the builder names the step
behind every problem."""

from functools import cache

import pytest

from app import settings
from app.defs import owners
from app.defs.loader import load_bundle
from app.defs.model import Bundle, DefError
from app.defs.validate import validate_bundle
from app.models.studio import InputField, PackDraft, StepDraft
from app.real_runs import DATE_PATTERN as RUN_DATE_PATTERN
from app.real_runs import single_date_field
from app.studio_build import (
    DATE_PATTERN,
    OrgRef,
    agent_definition,
    input_fields,
    input_schema,
    issue_of,
    outcomes,
    pack_definitions,
    pack_draft,
    pack_issues,
    readable_spaces,
    rules_of,
    step_of,
    tool_index,
)
from tests.team_seed import TEAM_AGENT, invoice_nudges

ORG = OrgRef("org_aaaa000000000001", "Harbor Cafe")
AGENT = owners.org_key(ORG.id, "invoice-helper")
KEY = owners.org_key(ORG.id, "invoice-nudges")
SEED_WORKFLOWS = ["overdue-invoice-follow-up", "refund-triage", "order-payment-reconciliation"]


@cache
def _files() -> Bundle:
    return load_bundle(settings.defs_dir())


@cache
def _bundle() -> Bundle:
    agent = agent_definition(AGENT, ORG, TEAM_AGENT, tool_index(_files()), 1)
    return Bundle(items={**_files().items, ("agent", AGENT): agent})


def _issues(draft: PackDraft, names=()):
    b = _bundle()
    agents = {d.key: d.body for d in b.of("agent")}
    spaces = {d.key for d in readable_spaces(b)}
    schemas = {d.key for d in b.of("schema")}
    return pack_issues(draft, tool_index(b), agents, spaces, schemas, names=names)


def _defs(draft: PackDraft, release: int = 1, key: str = KEY):
    b = _bundle()
    built = pack_definitions(key, ORG, draft, tool_index(b), {d.key: d.body for d in b.of("agent")}, release)
    return {(d.kind, d.key): d for d in built}


def _change(draft: PackDraft, step_id: str, **changes) -> PackDraft:
    steps = [s.model_copy(update=changes) if s.id == step_id else s for s in draft.steps]
    return draft.model_copy(update={"steps": steps})


def _route(draft: PackDraft, step_id: str, outcome: str, target: str | None) -> PackDraft:
    step = next(s for s in draft.steps if s.id == step_id)
    routes = {k: v for k, v in step.routes.items() if k != outcome}
    return _change(draft, step_id, routes=routes if target is None else {**routes, outcome: target})


def _config(draft: PackDraft, step_id: str, **config) -> PackDraft:
    step = next(s for s in draft.steps if s.id == step_id)
    return _change(draft, step_id, config={**step.config, **config})


def _add(draft: PackDraft, step: StepDraft) -> PackDraft:
    return draft.model_copy(update={"steps": [*draft.steps, step]})


def test_the_invoice_nudges_draft_has_no_issues():
    assert _issues(invoice_nudges(AGENT)) == []


def test_a_pack_draft_becomes_the_seed_pack_shapes_and_validates():
    by = _defs(invoice_nudges(AGENT))
    assert set(by) == {
        ("pack", KEY),
        ("workflow", KEY),
        ("contract", KEY),
        ("schema", f"{KEY}/input"),
        ("decision_rules", f"{KEY}--check"),
    }
    pack, workflow, contract = by[("pack", KEY)].body, by[("workflow", KEY)].body, by[("contract", KEY)].body
    assert pack["slug"] == KEY and pack["workflow"] == KEY and pack["contract"] == KEY
    assert pack["agents"] == [AGENT, "writer-agent"] and pack["connectors"] == ["gmail", "stripe"]
    assert (
        pack["version"] == "1.0.1" and pack["risk_class"] == "medium" and pack["publisher"] == "Harbor Cafe"
    )
    assert pack["price_note"] == "Built by your team. Up to $15.00 of AI work per run."
    assert workflow["entry_node_id"] == "start" and workflow["version"] == "1"
    check = next(n for n in workflow["nodes"] if n["id"] == "check")
    assert check["config"] == {"rules": f"{KEY}--check"}
    assert "routes" not in next(n for n in workflow["nodes"] if n["id"] == "done")
    assert contract["authorization"]["tool_capabilities"] == ["invoices.read", "mail.write"]
    assert contract["routes"] == {
        "success": "done",
        "failure": "failed",
        "timeout": "failed",
        "human_review": "review",
    }
    assert contract["capability"] == "team.invoice_nudges" and contract["org_id"] == "{org}"
    assert contract["output_schema_ref"] == "shared/drafts" and contract["version"] == 1
    assert validate_bundle(Bundle(items={**_bundle().items, **by})) == []


def test_a_pack_that_only_reads_is_low_risk():
    # The pack ends once a person has checked the plan: no writer, no approval, no Gmail step.
    kept = [s for s in DRAFT.steps if s.id not in ("draft", "approve", "send", "verify", "done")]
    only_reads = _route(DRAFT.model_copy(update={"steps": kept}), "review", "resolved", "nothing")
    assert _issues(only_reads) == []
    by = _defs(only_reads)
    assert by[("pack", KEY)].body["risk_class"] == "low"
    assert by[("pack", KEY)].body["agents"] == [AGENT] and by[("pack", KEY)].body["connectors"] == ["stripe"]
    assert by[("contract", KEY)].body["output_schema_ref"] == "shared/agent-result"
    assert by[("contract", KEY)].body["routes"]["success"] == "nothing"


@pytest.mark.parametrize(
    "key",
    [
        owners.org_key("org_bbbb000000000002", "invoice-nudges"),  # another org's namespace
        "invoice-nudges",  # a platform key
        owners.org_key(ORG.id, "Invoice Nudges"),  # not a key name
    ],
)
def test_a_pack_is_only_built_under_its_own_org(key):
    with pytest.raises(ValueError, match="key"):
        _defs(invoice_nudges(AGENT), key=key)


def test_the_input_schema_is_one_date_for_the_start_form():
    schema = input_schema("Invoice nudges", [InputField(name="as_of", label="As of", type="date")])
    assert DATE_PATTERN == RUN_DATE_PATTERN
    assert schema["required"] == ["as_of"] and schema["properties"]["as_of"]["title"] == "As of"
    assert single_date_field(schema) == "as_of"


def test_input_fields_read_back_from_their_schema():
    fields = [
        InputField(name="as_of", label="As of", type="date"),
        InputField(name="limit", label="Limit", type="number", required=False),
        InputField(name="note", label="Note", type="text"),
    ]
    assert input_fields(input_schema("Pack", fields)) == fields


def test_a_pack_reads_back_as_the_same_draft():
    draft = invoice_nudges(AGENT)
    by = {kind: d.body for (kind, _), d in _defs(draft, release=2).items()}
    rules = {"check": by["decision_rules"]}
    assert pack_draft(by["pack"], by["workflow"], by["contract"], by["schema"], rules) == draft


@pytest.mark.parametrize("slug", SEED_WORKFLOWS)
def test_a_seed_workflow_reads_as_steps(slug):
    nodes = _files().get("workflow", slug).body["nodes"]
    steps = [step_of(n) for n in nodes]
    assert [s.id for s in steps] == [n["id"] for n in nodes]
    connectors = [s for s in steps if s.type == "connector"]
    assert connectors and all("next" not in s.routes and "ok" in s.routes for s in connectors)
    assert all(s.config == {} for s in steps if s.type == "decision")


def test_a_decision_step_takes_its_outcomes_from_its_rules():
    node = next(n for n in _files().get("workflow", "refund-triage").body["nodes"] if n["id"] == "check")
    rules = rules_of(_files().get("decision_rules", node["config"]["rules"]).body)
    assert outcomes(step_of(node, rules)) == ["nothing", "human_review"]
    assert outcomes(step_of(node)) == []


DRAFT = invoice_nudges(AGENT)
CASES = {
    "a write not after an approval": (
        _route(DRAFT, "draft", "next", "send"),
        "send",
        "every path into it must come from an approval's granted outcome",
    ),
    "an unknown agent": (_config(DRAFT, "plan", agent="nobody"), "plan", "Choose the agent for step plan."),
    "an unknown tool": (_config(DRAFT, "invoices", tool="stripe.nothing"), "invoices", "Choose the app tool"),
    "a missing outcome": (
        _route(DRAFT, "verify", "fail", None),
        "verify",
        "The fail outcome of verify goes nowhere.",
    ),
    "an unknown target": (
        _route(DRAFT, "approve", "denied", "gone"),
        "approve",
        "goes to gone, which does not exist.",
    ),
    "a loop to itself": (_route(DRAFT, "approve", "timeout", "approve"), "approve", "goes back to itself."),
    "a route to the start": (
        _route(DRAFT, "approve", "timeout", "start"),
        "approve",
        "goes back to the start.",
    ),
    "an extra outcome": (_route(DRAFT, "plan", "error", "failed"), "plan", "plan has no error outcome."),
    "a step nothing leads to": (
        _add(DRAFT, StepDraft(id="orphan", type="end", config={"status": "COMPLETED"})),
        "orphan",
        "Nothing leads to step orphan.",
    ),
    "a decision without rules": (
        _change(DRAFT, "check", rules=None),
        "check",
        "Add the rules check decides with.",
    ),
    "a review that shows nothing": (
        _change(DRAFT, "review", config={"title": "Check"}),
        "review",
        "Choose what the reviewer is shown.",
    ),
    "an untitled approval": (_config(DRAFT, "approve", title=" "), "approve", "Give the approval a title."),
    "a memory step that writes": (
        _add(
            _route(DRAFT, "start", "next", "recall"),
            StepDraft(
                id="recall",
                type="memory",
                config={"op": "remember", "space": "customer-accounts", "text": "x"},
                routes={"next": "invoices"},
            ),
        ),
        "recall",
        "A memory step can only recall.",
    ),
    "an end step with outcomes": (
        _change(DRAFT, "failed", routes={"next": "done"}),
        "failed",
        "An end step has no outcomes.",
    ),
    "a verification with nothing to check": (
        _change(DRAFT, "verify", config={"value": "=nodes.draft.output"}),
        "verify",
        "Add a check or a result shape to verify.",
    ),
    "an unknown result shape": (
        _config(DRAFT, "draft", output_schema="shared/nothing"),
        "draft",
        "The result shape of draft does not exist.",
    ),
    # Preflight #26: a team agent always answers in the agent result shape.
    "a team agent with another result shape": (
        _config(DRAFT, "plan", output_schema="shared/drafts"),
        "plan",
        "plan runs an agent your team built, whose result is always the agent result shape.",
    ),
    "a seed agent with the agent result shape": (
        _config(DRAFT, "draft", output_schema="shared/agent-result"),
        "draft",
        "writer-agent answers only in its own result shape.",
    ),
    "a seed agent with another result shape": (
        _config(DRAFT, "draft", output_schema="refund-triage/triage"),
        "draft",
        "writer-agent answers only in its own result shape.",
    ),
    # Runtime fields the worker reads as they are.
    "a review with a bad time limit": (
        _config(DRAFT, "review", timeout_s="1 day"),
        "review",
        "The time limit of review must be a whole number of seconds, from 1 to 172800.",
    ),
    "an approval with a huge time limit": (
        _config(DRAFT, "approve", timeout_s=10**12),
        "approve",
        "The time limit of approve must be a whole number of seconds",
    ),
    "a repeat over a literal": (
        _config(DRAFT, "send", for_each=["a@example.com"]),
        "send",
        "The list send repeats over must be an expression",
    ),
    "checks that are one string": (
        _config(DRAFT, "verify", checks="=size(nodes.draft.output.drafts) > 0"),
        "verify",
        "The checks of verify must be a list of expressions, each starting with =.",
    ),
    "a check that is not an expression": (
        _config(DRAFT, "verify", checks=["size(nodes.draft.output.drafts) > 0"]),
        "verify",
        "The checks of verify must be a list of expressions",
    ),
    "a memory step with a bad limit": (
        _add(
            _route(DRAFT, "start", "next", "recall"),
            StepDraft(
                id="recall",
                type="memory",
                config={"space": "customer-accounts", "query": "nudges", "limit": 0},
                routes={"next": "invoices"},
            ),
        ),
        "recall",
        "The number of items recall recalls must be a whole number from 1 to 50.",
    ),
    # Preflight #7: app settings are checked against the tool's input schema.
    "a setting the tool does not have": (
        _config(DRAFT, "invoices", args={"status": "open", "limit": 100, "nope": 1}),
        "invoices",
        "stripe.list_invoices has no nope setting.",
    ),
    "a missing required setting": (
        _config(DRAFT, "send", args={"subject": "=item.subject", "body": "=item.body"}),
        "send",
        "send needs a value for recipient_email.",
    ),
    "a setting outside its choices": (
        _config(DRAFT, "invoices", args={"status": "nope"}),
        "invoices",
        "The status setting of invoices is not valid:",
    ),
    "a setting of the wrong type": (
        _config(DRAFT, "invoices", args={"status": "open", "limit": "many"}),
        "invoices",
        "The limit setting of invoices is not valid:",
    ),
    "settings that are not named values": (
        _config(DRAFT, "invoices", args="=input.args"),
        "invoices",
        "The settings of invoices must be named values.",
    ),
    # References are client JSON, so a reference that is not text is just a missing one.
    "a tool that is not text": (_config(DRAFT, "invoices", tool={"x": 1}), "invoices", "Choose the app tool"),
    "an agent that is not text": (
        _config(DRAFT, "plan", agent=["a"]),
        "plan",
        "Choose the agent for step plan.",
    ),
    "a result shape that is not text": (
        _config(DRAFT, "draft", output_schema=["shared/drafts"]),
        "draft",
        "The result shape of draft does not exist.",
    ),
    "a verification shape that is not text": (
        _config(DRAFT, "verify", schema={"a": 1}),
        "verify",
        "The result shape verify checks against does not exist.",
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_a_problem_names_its_step(case):
    draft, step, message = CASES[case]
    issues = _issues(draft)
    assert any(i.step == step and message in i.message for i in issues), issues


def test_arg_issues_say_where_they_are():
    issues = _issues(
        _config(DRAFT, "send", args={"subject": "=item.subject", "body": "=item.body", "cc": "x"})
    )
    assert sorted(i.path for i in issues) == [
        "steps.send.config.args.cc",
        "steps.send.config.args.recipient_email",
    ]


def test_nested_settings_are_checked_too():
    charges = StepDraft(
        id="charges",
        type="connector",
        config={"tool": "stripe.list_charges", "args": {"created": {"gte": "=int(input.since)", "lte": 5}}},
        routes={"ok": "plan", "denied": "failed", "error": "failed"},
    )
    draft = _add(_route(DRAFT, "start", "next", "charges"), charges)
    draft = _route(draft, "charges", "ok", "invoices")
    assert not [i for i in _issues(draft) if i.step == "charges"]
    bad = _config(draft, "charges", args={"created": {"gte": "x", "later": 1}})
    paths = {i.path for i in _issues(bad) if i.step == "charges"}
    assert paths == {"steps.charges.config.args.created.gte", "steps.charges.config.args.created.later"}


def test_a_tool_that_moves_money_is_refused():
    # No seed connector has a delete or money tool, so this one is made up for the test.
    b = _bundle()
    refund = {
        "id": "refund_charge",
        "action_class": "money",
        "capability": "payments.refund",
        "app": "Stripe",
    }
    tools = {**tool_index(b), "stripe.refund_charge": refund}
    draft = _config(DRAFT, "invoices", tool="stripe.refund_charge")
    agents = {d.key: d.body for d in b.of("agent")}
    spaces, schemas = {d.key for d in readable_spaces(b)}, {d.key for d in b.of("schema")}
    issues = pack_issues(draft, tools, agents, spaces, schemas, names=())
    assert any(i.step == "invoices" and "cannot delete records or move money" in i.message for i in issues)


def test_a_tool_of_an_unknown_action_class_needs_an_approval_too():
    # The write gate fails closed: only a read may run without an approval straight before it.
    b = _bundle()
    odd = {**tool_index(b)["stripe.list_invoices"], "action_class": "sync"}
    tools = {**tool_index(b), "stripe.sync_invoices": odd}
    draft = _config(DRAFT, "invoices", tool="stripe.sync_invoices")
    agents = {d.key: d.body for d in b.of("agent")}
    spaces, schemas = {d.key for d in readable_spaces(b)}, {d.key for d in b.of("schema")}
    issues = pack_issues(draft, tools, agents, spaces, schemas, names=())
    assert any(i.step == "invoices" and "approval's granted outcome" in i.message for i in issues)


def test_built_bodies_share_nothing_with_the_draft_or_each_other():
    draft = invoice_nudges(AGENT)
    by = _defs(draft)
    send = next(n for n in by[("workflow", KEY)].body["nodes"] if n["id"] == "send")
    send["config"]["args"]["subject"] = "changed"
    by[("pack", KEY)].body["deliverable_view"]["facts"].append({"label": "x", "value": "y"})
    assert next(s for s in draft.steps if s.id == "send").config["args"]["subject"] == "=item.subject"
    assert _defs(draft, release=2)[("pack", KEY)].body["deliverable_view"]["facts"] == []
    read = step_of(send)
    read.config["args"]["body"] = "changed"
    assert send["config"]["args"]["body"] == "=item.body"


def test_a_pack_that_never_completes_is_refused():
    draft = _config(_config(DRAFT, "done", status="FAILED"), "nothing", status="FAILED")
    assert any(i.message.startswith("The pack never completes.") for i in _issues(draft))


def test_a_pack_starts_at_its_one_start_step():
    assert any(i.path == "entry_step" for i in _issues(DRAFT.model_copy(update={"entry_step": "invoices"})))
    second = _add(DRAFT, StepDraft(id="again", type="trigger", routes={"next": "invoices"}))
    assert any(i.message == "A pack has exactly one start step." for i in _issues(second))


def test_input_fields_have_distinct_names():
    fields = [InputField(name="as_of", label="As of", type="date"), InputField(name="as_of", label="Again")]
    issues = _issues(DRAFT.model_copy(update={"input_fields": fields}))
    assert [i.path for i in issues] == ["input_fields[1]"]


def test_a_pack_name_is_unique_among_the_packs_the_org_sees():
    # Preflight #14: grants are keyed by pack name, so two visible packs never share one.
    assert _issues(DRAFT, names=["Refund Triage", " invoice NUDGES "]) == [
        _issues(DRAFT, names=["invoice nudges"])[0]
    ]
    issue = _issues(DRAFT, names=["invoice nudges"])[0]
    assert (issue.path, issue.step) == ("name", None) and "Invoice nudges" in issue.message
    assert _issues(DRAFT, names=["Refund Triage"]) == []


def test_validator_errors_name_their_step():
    at_node = DefError("workflow", KEY, "", "nodes[2] (plan).config.agent: agent 'x' does not exist")
    in_rules = DefError("decision_rules", f"{KEY}--check", "", "rules[0].when: CEL does not compile: x")
    issue = issue_of(at_node, KEY)
    assert (issue.step, issue.path) == ("plan", f"workflow/{KEY}")
    assert issue_of(in_rules, KEY).step == "check"
    assert issue_of(DefError("contract", KEY, "", "budget: bad"), KEY).step is None


def _with_second_write(*, also=("send2",), denied="failed", loop=False) -> PackDraft:
    """The invoice nudges pack with a second write after `send`, which the one approval also unlocks."""
    send = next(s for s in DRAFT.steps if s.id == "send")
    second = StepDraft(
        id="send2",
        type="connector",
        config=dict(send.config),
        routes={"ok": "send" if loop else "verify", "denied": "failed", "error": "failed"},
    )
    draft = _route(_route(DRAFT, "send", "ok", "send2"), "approve", "denied", denied)
    draft = _config(draft, "approve", also_unlocks=list(also))
    return _add(draft, second)


def test_an_approval_may_also_unlock_a_write_that_follows_its_granted_step():
    assert _issues(_with_second_write()) == []


def test_also_unlocks_refuses_a_write_a_denied_approval_reaches():
    issues = _issues(_with_second_write(denied="send2"))
    assert any(i.step == "send2" and "denied or times out" in i.message for i in issues), issues


def test_also_unlocks_refuses_a_read():
    issues = _issues(_with_second_write(also=("invoices",)))
    assert any("not a step that changes data" in i.message for i in issues), issues


def test_also_unlocks_refuses_a_write_on_a_loop():
    issues = _issues(_with_second_write(loop=True))
    assert any(i.step == "send2" and "loop" in i.message for i in issues), issues
