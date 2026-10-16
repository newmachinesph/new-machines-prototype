"""The fake-model registry for the sample packs, its shared helpers, the writer's sign-off and the provider
falling back to the registry."""

from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from app import settings
from app.defs.loader import load_bundle
from app.runtime import fakes, providers
from app.runtime.fakes import _shared


def _script(result):
    return lambda inputs: result


def test_collect_merges_every_module_s_agents_and_answers():
    one = SimpleNamespace(AGENTS={"a-agent": _script({})}, JEV={"q_one": lambda state: {"noul": 1.0}})
    two = SimpleNamespace(AGENTS={"b-agent": _script({})})
    agents, answers = fakes._collect([one, two])
    assert set(agents) == {"a-agent", "b-agent"} and set(answers) == {"q_one"}


@pytest.mark.parametrize("field", ["AGENTS", "JEV"])
def test_collect_refuses_a_name_defined_twice(field):
    one = SimpleNamespace(**{field: {"same": _script({})}})
    two = SimpleNamespace(**{field: {"same": _script({})}})
    with pytest.raises(ValueError, match="same"):
        fakes._collect([one, two])


def test_every_pack_module_loads():
    fakes._registry.cache_clear()
    agents, answers = fakes._registry()
    assert isinstance(agents, dict) and isinstance(answers, dict)
    assert fakes.agent_script("no-such-agent") is None and fakes.jev_answer("no_such_question") is None


def test_the_provider_falls_back_to_the_registry(monkeypatch):
    monkeypatch.setattr(
        fakes,
        "agent_script",
        lambda agent_id: (lambda inputs: {"echo": inputs}) if agent_id == "probe-agent" else None,
    )
    turn = providers.FakeProvider().call(
        model="fake-fast",
        system=f"{providers.AGENT_MARKER}probe-agent\nYou are a probe.",
        messages=[{"role": "user", "content": '# Inputs\n```json\n{"a": 1}\n```'}],
        tools=[],
        max_tokens=100,
    )
    assert turn.content[0]["input"] == {"echo": {"a": 1}}
    with pytest.raises(LookupError):
        providers.FakeProvider().call(
            model="fake-fast",
            system=f"{providers.AGENT_MARKER}nobody\n",
            messages=[],
            tools=[],
            max_tokens=10,
        )


ITEM = {"to": "ana@example.com", "about": "Your question", "facts": ["Thanks for writing."], "ref": "r1"}


def test_the_writer_signs_off_with_the_name_it_is_given():
    [draft] = providers.fake_writer(
        {"items": [ITEM], "review": None, "tone": "warm", "sign_off": "Support team"}
    )["drafts"]
    assert draft["body"].endswith("Kind regards,\nSupport team")
    [draft] = providers.fake_writer({"items": [ITEM], "review": None, "tone": "warm"})["drafts"]
    assert draft["body"].endswith(providers.SIGN_OFF)  # unchanged for the existing packs


def test_the_draft_request_schema_takes_an_optional_sign_off():
    schema = load_bundle(settings.defs_dir()).get("schema", "shared/draft-request").body
    validator = Draft202012Validator(schema)
    base = {"items": [ITEM], "review": None, "tone": "warm"}
    assert not list(validator.iter_errors(base))
    assert not list(validator.iter_errors({**base, "sign_off": "Alex Tan"}))
    assert list(validator.iter_errors({**base, "sign_off": ""}))
    assert list(validator.iter_errors({**base, "sign_off": "x" * 81}))


def test_the_writer_skill_describes_the_sign_off():
    text = (settings.defs_dir() / "agents" / "writer-agent" / "skills" / "write-drafts.md").read_text(
        encoding="utf-8"
    )
    assert "`sign_off`" in text and "Accounts team" in text


def test_shared_helpers():
    assert _shared.sender("Maya Chen <maya.chen@brightleaf.example.com>") == (
        "Maya Chen",
        "maya.chen@brightleaf.example.com",
    )
    assert _shared.sender("tom@okaforlegal.example.com") == ("", "tom@okaforlegal.example.com")
    assert _shared.messages({"messages": [{"a": 1}, "x"]}) == [{"a": 1}]
    assert _shared.messages([{"a": 1}]) == [{"a": 1}] and _shared.messages(None) == []
    assert _shared.day("2026-10-15T09:30:00Z") == "2026-10-15"
    assert _shared.money_minor("48.50") == 4850
    assert _shared.money_minor("$1,234.5") == 123450
    assert _shared.money_minor("615") == 61500
    assert _shared.money_minor("n/a") is None and _shared.money_minor("") is None
    assert _shared.money_text(92965) == "929.65 USD" and _shared.money_text(-5) == "-0.05 USD"
    assert _shared.has_word("Could you send a quote?", "quote") is True
    assert _shared.has_word("I quoted you", "quote") is False
    assert _shared.field("From: Maya\nSubject: Booking\nText: Hi", "Subject") == "Booking"
    assert _shared.field("From: Maya", "Subject") == ""


def _sheet(*rows: list[str]) -> dict:
    header = ["Date", "Description", "Amount", "Paid by", "Receipt"]
    return {"valueRanges": [{"values": [header, *rows]}]}


def test_one_expense_reads_in_the_singular():
    taxi = ["2026-10-05", "Taxi to client", "60.00", "Alex Tan", "no"]
    one = fakes.agent_script("expense-agent")({"sheet": _sheet(taxi), "week_start": "2026-10-05"})
    assert one["summary"] == (
        "1 expense from 2026-10-05 to 2026-10-11, 60.00 USD in total; 1 flagged for a check."
    )
    assert one["email_facts"] == [
        "Expenses from 2026-10-05 to 2026-10-11: 1 item, 60.00 USD in total.",
        "Travel: 1 item, 60.00 USD.",
        "1 expense is flagged for a check: Row 2 (No receipt for $25 or more).",
    ]
    train = ["2026-10-06", "Train home", "700.00", "Alex Tan", "yes"]
    two = fakes.agent_script("expense-agent")({"sheet": _sheet(taxi, train), "week_start": "2026-10-05"})
    assert two["summary"].startswith("2 expenses from 2026-10-05")
    assert two["email_facts"][:2] == [
        "Expenses from 2026-10-05 to 2026-10-11: 2 items, 760.00 USD in total.",
        "Travel: 2 items, 760.00 USD.",
    ]
    assert two["email_facts"][2].startswith("2 expenses are flagged for a check: ")


def test_one_meeting_reads_in_the_singular():
    event = {
        "id": "e1",
        "summary": "Kick-off",
        "start": {"dateTime": "2026-10-15T09:00:00Z"},
        "attendees": [
            {"email": "alex@yourco.example.com", "self": True},
            {"email": "ana@client.example.com", "responseStatus": "accepted"},
        ],
    }
    meeting_agent = fakes.agent_script("meeting-agent")
    one = meeting_agent({"events": {"items": [event]}, "day": "2026-10-15"})
    assert one["summary"] == "Read 1 meeting on 2026-10-15 and planned 1 follow-up."
    two = meeting_agent({"events": {"items": [event, event]}, "day": "2026-10-15"})
    assert two["summary"] == "Read 2 meetings on 2026-10-15 and planned 2 follow-ups."
