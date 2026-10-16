"""The Exception Desk connector against a running MongoDB MCP server (NM_MCP_URL) holding the demo database:
every read answers the shape its sandbox fixture records, the planted cases come back with the fixture's
amounts, and the two note writes answer from sandbox data without reaching the read-only server. Skipped
without NM_MCP_URL."""

import json
import os

import pytest

from app import settings
from app.runtime import drivers, mcp
from tests import sample_packs as sp
from tests.test_mcp_driver import CONNECTOR, PACK, READS

pytestmark = pytest.mark.skipif(not os.environ.get("NM_MCP_URL"), reason="NM_MCP_URL is not set")

WINDOW = {"since": "2026-07-18T00:00:00Z", "until": "2026-10-16T23:59:59Z"}  # holds every planted case
PLANTED = ["DEMO-SNP-1", "DEMO-PPC-1", "DEMO-DSP-1", "DEMO-PNS-1"]
AMOUNTS = {"DEMO-SNP-1": 40252.8, "DEMO-PPC-1": 15600.0, "DEMO-DSP-1": 28800.0, "DEMO-PNS-1": 18600.0}


def _tool(connector: str, tool_id: str) -> dict:
    return next(t for t in sp.body("connector", connector)["tools"] if t["id"] == tool_id)


def _fixture(connector: str, tool_id: str) -> list[dict]:
    path = settings.defs_dir() / "packs" / PACK / "sandbox" / connector / f"{tool_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))[READS[(connector, tool_id)]]


def _rows(driver, connector: str, tool_id: str, args: dict) -> list[dict]:
    result = driver.execute(connector, _tool(connector, tool_id), args)
    assert result.ok, result.error
    assert result.mocked is False
    return result.data[READS[(connector, tool_id)]]


@pytest.fixture(scope="module")
def driver():
    live = drivers.McpDriver()
    assert live.is_available()
    return live


def _by_order(rows: list[dict]) -> dict[str, dict]:
    key = "id" if rows and "id" in rows[0] and "order_id" not in rows[0] else "order_id"
    return {r[key]: r for r in rows if str(r.get(key, "")).startswith("DEMO-")}


@pytest.mark.parametrize(("connector", "tool_id"), sorted(READS))
def test_each_read_answers_the_fixture_s_shape_and_the_planted_rows(driver, connector, tool_id):
    args = (
        {}
        if tool_id == "list_customers"
        else {**WINDOW, **({"limit": 2000} if tool_id == "list_store_orders" else {})}
    )
    rows = _rows(driver, connector, tool_id, args)
    fixture = _fixture(connector, tool_id)
    assert rows and all(list(r) == list(fixture[0]) for r in rows)
    if tool_id == "list_customers":
        planted = {r["id"]: r for r in fixture if r["id"].startswith("DEMO-CUST-")}
        live = {r["id"]: r for r in rows if r["id"] in planted}
    else:
        planted, live = _by_order(fixture), _by_order(rows)
    assert set(planted) <= set(live), sorted(set(planted) - set(live))
    for order_id, row in planted.items():
        assert live[order_id] == row, order_id


def test_the_planted_cases_carry_the_fixture_s_amounts(driver):
    orders = _by_order(_rows(driver, CONNECTOR, "list_store_orders", {**WINDOW, "limit": 2000}))
    invoices = _by_order(_rows(driver, CONNECTOR, "list_sales_orders", WINDOW))
    sales = _by_order(_rows(driver, CONNECTOR, "list_sales", WINDOW))
    for order_id, amount in AMOUNTS.items():
        assert orders[order_id]["grand_total"] == amount, order_id
        assert invoices[order_id]["grand_total"] == amount, order_id
        assert sales[order_id]["total"] == amount, order_id
    assert orders["DEMO-PNS-1"]["paid"] and not orders["DEMO-PNS-1"]["scanned_out"]
    assert invoices["DEMO-SNP-1"]["balance"] == 40252.8 and invoices["DEMO-SNP-1"]["delivered"]
    assert (
        invoices["DEMO-PNS-1"]["balance"] == 0.0
        and invoices["DEMO-PNS-1"]["total_payment_received"] == 18600.0
    )
    payments = _by_order(_rows(driver, CONNECTOR, "list_store_payments", WINDOW))
    assert (payments["DEMO-PPC-1"]["amount"], payments["DEMO-PPC-1"]["status"]) == (15600.0, "pending")
    assert (payments["DEMO-PNS-1"]["amount"], payments["DEMO-PNS-1"]["status"]) == (18600.0, "confirmed")
    posted = _by_order(_rows(driver, CONNECTOR, "list_customer_payments", WINDOW))
    assert posted["DEMO-PNS-1"]["amount"] == 18600.0 and "DEMO-SNP-1" not in posted
    served = _by_order(_rows(driver, CONNECTOR, "list_served_orders", WINDOW))
    assert served["DEMO-SNP-1"]["delivered"] and served["DEMO-SNP-1"]["delivery_count"] == 1
    assert "DEMO-PNS-1" not in served
    customers = {c["id"]: c for c in _rows(driver, CONNECTOR, "list_customers", {})}
    assert customers["DEMO-CUST-DSP-1"]["balance_overdue"] == 28800.0
    assert "credit memo" in customers["DEMO-CUST-DSP-1"]["notes"][0]


def test_the_server_is_read_only_and_a_note_write_answers_from_sandbox(driver):
    """The two writes carry no mapping: they never reach the server, which registers no write tools."""
    tools = mcp.McpClient(settings.mcp_url(), token=settings.mcp_token()).list_tools()
    assert "find" in tools and "aggregate" in tools
    assert not {"update-many", "insert-many", "delete-many"} & set(tools), "start the server with --readOnly"
    body = sp.body("connector", CONNECTOR)
    for tool_id in ("add_ledger_note", "add_warehouse_note"):
        tool = _tool(CONNECTOR, tool_id)
        chosen = drivers.driver_for(body, "live", pack=PACK, tool=tool)
        assert isinstance(chosen, drivers.SandboxDriver)
        result = chosen.execute(CONNECTOR, tool, {"order_id": "DEMO-SNP-1", "note": "Exception desk check"})
        recorded = settings.defs_dir() / "connectors" / "sandbox" / CONNECTOR / f"{tool_id}.json"
        expected = json.loads(recorded.read_text("utf-8"))
        assert result == drivers.ToolResult(ok=True, data=expected, mocked=True)
    served = _by_order(_rows(driver, CONNECTOR, "list_served_orders", WINDOW))
    assert "Exception desk check" not in served["DEMO-SNP-1"]["notes"]
