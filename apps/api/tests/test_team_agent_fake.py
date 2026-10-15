"""Sub-project C, part 3: under the fake model, any team agent (whose result is shared/agent-result) answers
deterministically from its inputs, so a team pack runs end to end in tests and in the sandbox."""

import pytest

from app.runtime import providers
from app.runtime.agent import build_user_message
from app.runtime.providers import SUBMIT_TOOL, FakeProvider, ToolSpec
from tests.test_seed_packs import AS_OF, _sandbox, _schema, _valid


def _submit(schema: dict) -> ToolSpec:
    return ToolSpec(name=SUBMIT_TOOL, description="Submit the result.", input_schema=schema)


def _result_schema() -> dict:
    return {k: v for k, v in _schema("shared/agent-result").items() if k != "$schema"}


def test_the_team_script_plans_from_the_first_open_records():
    result = providers.fake_team_agent({"as_of": AS_OF, "invoices": _sandbox("stripe", "list_invoices")})
    _valid("shared/agent-result", result)
    _valid("shared/review-items", result["review_items"])
    assert [m["ref"] for m in result["messages"]] == ["INV-0107", "INV-0098", "INV-0086"]
    assert result["messages"][0] == {
        "to": "accounts.harborcafe@example.net",
        "about": "About INV-0107",
        "facts": ["Reference: INV-0107."],
        "ref": "INV-0107",
    }
    assert [i["amount_minor"] for i in result["review_items"]] == [48000, 125000, 31250]
    assert {i["currency"] for i in result["review_items"]} == {"USD"}
    assert result["summary"] == "Prepared 3 messages from the inputs."


def test_the_team_script_with_no_records_has_nothing_to_do():
    result = providers.fake_team_agent({"note": "hello"})
    _valid("shared/agent-result", result)
    assert result == {"summary": "Nothing to work on in the inputs.", "messages": [], "review_items": []}


def test_the_team_script_counts_one_message_in_the_singular():
    result = providers.fake_team_agent({"rows": [{"id": "r-1", "status": "open", "amount": 100}]})
    _valid("shared/agent-result", result)
    assert result["summary"] == "Prepared 1 message from the inputs."


def test_the_team_script_reads_orders_with_a_decimal_total_price():
    result = providers.fake_team_agent(
        {"orders": {"orders": [{"name": "#1001", "total_price": "12.34", "currency": "eur"}]}}
    )
    _valid("shared/agent-result", result)
    [item] = result["review_items"]
    assert (item["ref"], item["amount_minor"], item["currency"]) == ("#1001", 1234, "EUR")


def test_the_team_script_dates_a_record_without_a_usable_date_on_the_fake_day():
    result = providers.fake_team_agent({"rows": [{"id": "r-1"}, {"id": "r-2", "created": "not a date"}]})
    assert [i["date"] for i in result["review_items"]] == [providers.FAKE_TEAM_DATE] * 2


def test_the_team_script_skips_an_empty_envelope_list_for_a_filled_one():
    result = providers.fake_team_agent({"shop": {"data": [], "orders": [{"id": "o-1"}]}})
    assert [m["ref"] for m in result["messages"]] == ["o-1"]


def test_the_team_script_treats_an_unreadable_total_price_as_zero():
    result = providers.fake_team_agent({"rows": [{"id": "r-1", "total_price": "free"}]})
    assert result["review_items"][0]["amount_minor"] == 0


def test_the_team_script_does_not_take_a_boolean_for_an_amount():
    result = providers.fake_team_agent({"rows": [{"id": "r-1", "amount_due": True, "amount": 250}]})
    assert result["review_items"][0]["amount_minor"] == 250


def test_the_team_script_falls_back_to_the_default_currency_for_an_odd_code():
    result = providers.fake_team_agent(
        {"rows": [{"id": "r-1", "currency": "dollars"}, {"id": "r-2", "currency": 1}]}
    )
    _valid("shared/review-items", result["review_items"])
    assert [i["currency"] for i in result["review_items"]] == ["USD", "USD"]


def test_a_scripted_seed_agent_still_wins_over_the_team_script():
    turn = FakeProvider().call(
        model="fake-fast",
        system="agent:writer-agent\nYou write drafts.",
        messages=[{"role": "user", "content": build_user_message("Write.", {"items": []})}],
        tools=[_submit(_result_schema())],
        max_tokens=1000,
    )
    [block] = turn.content
    assert block["input"] == {"drafts": []}


def test_the_fake_provider_answers_any_agent_whose_result_is_an_agent_result():
    inputs = {"as_of": AS_OF, "invoices": _sandbox("stripe", "list_invoices")}
    turn = FakeProvider().call(
        model="fake-fast",
        system="agent:org-aaaa000000000001--invoice-helper\nYou help the accounts team.",
        messages=[{"role": "user", "content": build_user_message("Plan the nudges.", inputs)}],
        tools=[_submit(_result_schema())],
        max_tokens=1000,
    )
    [block] = turn.content
    assert (
        block["name"] == SUBMIT_TOOL and block["input"]["summary"] == "Prepared 3 messages from the inputs."
    )


def test_the_fake_provider_still_refuses_an_agent_it_has_no_script_for():
    with pytest.raises(LookupError, match="no script"):
        FakeProvider().call(
            model="fake-fast",
            system="agent:someone-else\nHello.",
            messages=[{"role": "user", "content": build_user_message("Do it.", {})}],
            tools=[_submit({"title": "Something else", "type": "object"})],
            max_tokens=1000,
        )
