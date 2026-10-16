"""The MCP client against the in-process FastMCP server: tools listed with their hints, calls with
structured and failed results, and the server-address rules on real sessions."""
# ruff: noqa: F811

import time
from datetime import timedelta

import anyio
import httpx
import pytest

from app.custom_mcp import client, safety
from tests.fake_mcp import HOST, PUBLIC_IP, TOKEN, URL, fake_mcp, many_server, start_fake  # noqa: F401


def test_the_tools_are_listed_with_their_hints(fake_mcp):
    tools = {t.name: t for t in client.list_tools(URL, "Authorization", TOKEN)}
    assert sorted(tools) == [
        "delete_customer",
        "get_broken_report",
        "get_customer",
        "list_orders",
        "refund_payment",
        "update_customer_note",
    ]
    assert tools["get_customer"].read_only is True
    assert tools["get_customer"].input_schema["required"] == ["customer_id"]
    assert tools["get_customer"].output_schema["properties"]["email"]["type"] == "string"
    assert tools["delete_customer"].destructive is True
    assert tools["update_customer_note"].read_only is None


def test_the_address_is_resolved_once_and_pinned_for_the_session(fake_mcp, monkeypatch):
    answers = iter([[PUBLIC_IP], ["127.0.0.1"]])
    asked: list[str] = []

    def resolve(host: str, port: int) -> list[str]:
        asked.append(host)
        return next(answers)

    monkeypatch.setattr(safety, "resolve", resolve)
    assert len(client.list_tools(URL, "Authorization", TOKEN)) == 6
    assert asked == [HOST]  # one lookup for the whole session
    assert {httpx.URL(u).host for u in fake_mcp.urls} == {PUBLIC_IP}
    assert set(fake_mcp.hosts) == {HOST}
    assert set(fake_mcp.sni) == {HOST}
    with pytest.raises(safety.UrlRefused):  # the next session looks again, and now refuses
        client.list_tools(URL, "Authorization", TOKEN)


def test_a_redirect_is_not_followed(fake_mcp):
    with pytest.raises(client.McpUnreachable):
        client.list_tools(f"https://{HOST}/moved", "Authorization", TOKEN)
    assert "/moved" in fake_mcp.paths
    assert "/mcp" not in fake_mcp.paths


def test_a_wrong_token_is_unreachable(fake_mcp):
    with pytest.raises(client.McpUnreachable):
        client.list_tools(URL, "Authorization", "wrong-token")


def test_an_api_key_header_carries_the_token_as_it_is(fake_mcp):
    assert len(client.list_tools(URL, "X-Api-Key", TOKEN)) == 6


def test_a_call_returns_the_structured_result(fake_mcp):
    outcome = client.call_tool(URL, "Authorization", TOKEN, "get_customer", {"customer_id": "c_1"})
    assert outcome == client.CallOutcome(
        ok=True, data={"id": "c_1", "name": "Ada Lovelace", "email": "ada@example.com"}
    )


def test_a_tool_error_is_a_failed_outcome(fake_mcp):
    outcome = client.call_tool(URL, "Authorization", TOKEN, "get_broken_report", {})
    assert outcome.ok is False and outcome.data is None
    assert "report service is down" in (outcome.message or "")


def test_no_log_record_carries_the_query_string(fake_mcp, caplog):
    import logging

    caplog.set_level(logging.INFO)
    client.list_tools(f"{URL}?key=SECRETVALUE", "Authorization", TOKEN)
    assert "SECRETVALUE" not in " ".join(r.getMessage() for r in caplog.records)


def test_an_sdk_error_log_keeps_the_type_but_not_the_address(caplog):
    import logging

    request = httpx.Request("POST", f"{URL}?key=SECRETVALUE")
    response = httpx.Response(500, request=request)
    text = f"Server error '500' for url '{request.url}'"
    error = httpx.HTTPStatusError(text, request=request, response=response)
    try:
        raise error
    except httpx.HTTPStatusError:
        logging.getLogger("mcp.client.streamable_http").exception("Error in post_writer")
    record = next(r for r in caplog.records if r.name == "mcp.client.streamable_http")
    assert record.getMessage() == "Error in post_writer: HTTPStatusError"
    assert record.exc_info is None
    assert "SECRETVALUE" not in caplog.text


def test_the_call_deadline_is_shorter_than_the_activity_that_runs_it():
    from app.worker import workflow

    assert timedelta(seconds=client.TIMEOUT_S) < workflow._TOOL_TIMEOUT


def test_a_slow_tool_gives_up_at_the_timeout(fake_mcp, monkeypatch):
    async def slow_report() -> str:
        import anyio

        await anyio.sleep(4)
        return "late"

    fake_mcp.server.add_tool(slow_report, name="slow_report", description="A slow report.")
    monkeypatch.setattr(client, "TIMEOUT_S", 1.5)
    started = time.monotonic()
    with pytest.raises(client.McpUnreachable):
        client.call_tool(URL, "Authorization", TOKEN, "slow_report", {})
    assert time.monotonic() - started < 4


def test_a_response_over_1_mb_is_unreachable(fake_mcp):
    def huge_report() -> str:
        return "x" * (safety.MAX_RESPONSE_BYTES + 10)

    fake_mcp.server.add_tool(huge_report, name="huge_report", description="A huge report.")
    with pytest.raises(client.McpUnreachable):
        client.call_tool(URL, "Authorization", TOKEN, "huge_report", {})


def test_at_most_100_tools_are_taken(monkeypatch):
    fake = start_fake(monkeypatch, many_server(120))
    try:
        listed = client.list_tools(URL, "Authorization", TOKEN)
    finally:
        fake.stop()
    assert len(listed) == 100
    assert listed[0].name == "get_item_000" and listed[-1].name == "get_item_099"


def test_an_http_address_never_reaches_the_server(fake_mcp):
    with pytest.raises(safety.UrlRefused):
        client.list_tools(f"http://{HOST}/mcp", "Authorization", TOKEN)
    assert fake_mcp.paths == []


def test_a_host_that_does_not_resolve_is_unreachable(fake_mcp, monkeypatch):
    def nowhere(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    monkeypatch.setattr(safety, "resolve", nowhere)
    with pytest.raises(client.McpUnreachable):
        client.list_tools(URL, "Authorization", TOKEN)


def test_a_slow_lookup_counts_against_the_deadline(fake_mcp, monkeypatch):
    def stuck(host: str, port: int) -> list[str]:
        time.sleep(3)
        return [PUBLIC_IP]

    monkeypatch.setattr(safety, "resolve", stuck)
    monkeypatch.setattr(client, "TIMEOUT_S", 0.5)
    started = time.monotonic()
    with pytest.raises(client.McpUnreachable):
        client.list_tools(URL, "Authorization", TOKEN)
    assert time.monotonic() - started < 2.5


def test_a_streamed_body_over_1_mb_with_no_length_fails_at_once(monkeypatch):
    sent = 0

    async def endless():
        nonlocal sent
        while True:
            sent += 64 * 1024
            yield b"x" * 64 * 1024
            await anyio.sleep(0.001)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=endless(), headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(safety, "resolve", lambda host, port: [PUBLIC_IP])
    monkeypatch.setattr(client, "_inner_transport", lambda: httpx.MockTransport(handler))
    monkeypatch.setattr(client, "TIMEOUT_S", 20.0)
    started = time.monotonic()
    with pytest.raises(client.McpUnreachable):
        client.list_tools(URL, "Authorization", TOKEN)
    assert time.monotonic() - started < 5  # not the 20 s deadline
    assert sent <= safety.MAX_RESPONSE_BYTES + 128 * 1024  # it stopped reading
