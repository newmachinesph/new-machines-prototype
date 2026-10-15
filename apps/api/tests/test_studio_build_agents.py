"""Sub-project C, part 4: an agent draft becomes a google_adk agent definition, and back."""

from functools import cache

import pytest
from pydantic import ValidationError

from app import settings
from app.defs import owners
from app.defs.loader import load_bundle
from app.defs.model import Bundle
from app.defs.validate import validate_bundle
from app.models.studio import AgentDraft, SkillDraft
from app.studio_build import OrgRef, agent_definition, agent_draft, agent_issues, readable_spaces, tool_index
from tests.team_seed import TEAM_AGENT

ORG = OrgRef("org_aaaa000000000001", "Harbor Cafe")
KEY = owners.org_key(ORG.id, "invoice-helper")


@cache
def _bundle() -> Bundle:
    return load_bundle(settings.defs_dir())


def test_the_tool_index_names_each_tool_with_its_app():
    tools = tool_index(_bundle())
    assert tools["stripe.list_invoices"]["app"] == "Stripe"
    assert tools["gmail.create_draft"]["action_class"] == "write"


def test_every_seed_memory_space_is_readable_by_team_agents():
    assert {d.key for d in readable_spaces(_bundle())} == {"customer-accounts", "retail-commerce"}


def test_an_agent_draft_becomes_a_valid_google_adk_agent():
    d = agent_definition(KEY, ORG, TEAM_AGENT, tool_index(_bundle()), 1)
    assert d.body["runtime"] == {
        "adapter": "google_adk",
        "model_profile": "fast",
        "instructions": "instructions.md",
        "skills": ["skills/01-find-open-invoices.md"],
        "tools": ["stripe.list_invoices"],
        "max_turns": 4,
    }
    assert d.body["agent_id"] == KEY and d.body["version"] == "1.0.1"
    assert d.body["publisher_id"] == "org-aaaa000000000001" and d.body["publisher_name"] == "Harbor Cafe"
    assert d.body["requested_tool_capabilities"] == ["invoices.read"]
    assert (d.body["input_schema_ref"], d.body["output_schema_ref"]) == (
        "shared/agent-input",
        "shared/agent-result",
    )
    assert d.files["skills/01-find-open-invoices.md"].startswith("# Find open invoices\n\n")
    assert validate_bundle(Bundle(items={**_bundle().items, ("agent", KEY): d})) == []


def test_an_agent_reads_back_as_the_same_draft():
    d = agent_definition(KEY, ORG, TEAM_AGENT, tool_index(_bundle()), 3)
    assert agent_draft(d.body, d.files) == TEAM_AGENT


def test_a_skill_title_with_punctuation_reads_back_unchanged():
    skill = SkillDraft(
        title="Check: due dates & amounts (USD)!", text="Compare each amount with the invoice."
    )
    draft = TEAM_AGENT.model_copy(update={"skills": [skill]})
    d = agent_definition(KEY, ORG, draft, tool_index(_bundle()), 1)
    assert d.body["runtime"]["skills"] == ["skills/01-check-due-dates-amounts-usd.md"]
    assert agent_draft(d.body, d.files).skills == [skill]


@pytest.mark.parametrize(
    "key",
    [
        owners.org_key("org_bbbb000000000002", "invoice-helper"),  # another org's namespace
        "invoice-helper",  # a platform key
        owners.org_key(ORG.id, "Invoice Helper"),  # not a key name
        owners.org_key(ORG.id, "x" * 41),  # too long
    ],
)
def test_an_agent_is_only_built_under_its_own_org(key):
    with pytest.raises(ValueError, match="key"):
        agent_definition(key, ORG, TEAM_AGENT, tool_index(_bundle()), 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", " \t "),
        ("summary", "\n\n"),
        ("instructions", "   "),
        ("skills", [{"title": "  ", "text": "Fine."}]),
        ("skills", [{"title": "Fine", "text": " \n "}]),
    ],
)
def test_a_whitespace_only_field_is_refused_on_save(field, value):
    with pytest.raises(ValidationError):
        AgentDraft.model_validate({**TEAM_AGENT.model_dump(), field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "Invoice\nhelper"),
        ("summary", "Line one.\r\nLine two."),
        ("skills", [{"title": "A\nB", "text": "C"}]),
    ],
)
def test_a_title_must_be_one_line(field, value):
    with pytest.raises(ValidationError):
        AgentDraft.model_validate({**TEAM_AGENT.model_dump(), field: value})


def test_surrounding_whitespace_is_stripped_on_save():
    draft = AgentDraft.model_validate({**TEAM_AGENT.model_dump(), "name": "  Invoice helper \n"})
    assert draft == TEAM_AGENT


@pytest.mark.parametrize(
    ("tools", "message"),
    [
        (["stripe.list_invoices", "stripe.list_invoices"], "stripe.list_invoices is listed twice."),
        (["nope.tool"], "nope.tool is not a tool of any app."),
        (["gmail.create_draft"], "An agent may only read."),
    ],
)
def test_agent_issues_name_the_tool(tools, message):
    issues = agent_issues(TEAM_AGENT.model_copy(update={"tools": tools}), tool_index(_bundle()))
    assert [i.path for i in issues] == [f"tools[{len(tools) - 1}]"]
    assert issues[0].message.startswith(message)


def test_a_draft_with_read_tools_has_no_issues():
    assert agent_issues(TEAM_AGENT, tool_index(_bundle())) == []
