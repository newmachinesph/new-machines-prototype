"""The customer agent catalog: definition agents (and, in the demo workspace, sample agents) with the skills,
tools and model profile they run with, and the packs that use them."""

import pytest
from fastapi.testclient import TestClient

from app import settings, temporal_client
from app.catalog.agents import humanise, skill_title
from app.defs import registry
from app.defs.loader import load_bundle
from app.defs.validate import validate_bundle
from app.main import create_app
from app.runtime import drivers
from app.store import reset_store

PACK = "order-payment-reconciliation"
RECON = {"slug": PACK, "name": "Order & Payment Reconciliation"}
INVOICES = {"slug": "overdue-invoice-follow-up", "name": "Overdue Invoice Follow-up"}
INVENTORY = {"slug": "weekly-inventory-report", "name": "Weekly Inventory Report"}
REFUNDS = {"slug": "refund-triage", "name": "Refund Triage"}
DEFINITION_AGENTS = ["finance-agent", "ops-agent", "retail-agent"]


def by_id(agents: list[dict]) -> dict[str, dict]:
    return {a["id"]: a for a in agents}


# --- helpers (pure) ---------------------------------------------------------------------------------------


def test_skill_title_is_the_first_heading_after_front_matter():
    text = "---\nname: match-orders\ndescription: x\n---\n\nIntro line.\n\n## Pair orders\n\n# Later\n"
    assert skill_title("skills/match-orders.md", text) == "Pair orders"


def test_skill_title_falls_back_to_the_humanised_file_stem():
    text = "---\nname: match-orders\n---\n\nNo heading here.\n```\n# not a heading in code\n```\n"
    assert skill_title("skills/match-orders.md", text) == "Match orders"
    assert skill_title("skills/explain_mismatch.md", None) == "Explain mismatch"


def test_humanise():
    assert humanise("new-machines-labs") == "New machines labs"
    assert humanise("new-machines-labs", title=True) == "New Machines Labs"


def test_workspace_mode_defaults_to_demo(monkeypatch):
    monkeypatch.delenv("NM_WORKSPACE", raising=False)
    assert settings.workspace_mode() == "demo"
    monkeypatch.setenv("NM_WORKSPACE", "live")
    assert settings.workspace_mode() == "live"


# --- definitions ------------------------------------------------------------------------------------------


def test_agent_definitions_carry_customer_copy():
    bundle = load_bundle(settings.defs_dir())
    for key in DEFINITION_AGENTS:
        body = bundle.get("agent", key).body
        assert 0 < len(body["name"]) <= 80
        assert 0 < len(body["summary"]) <= 280
        assert body["publisher_name"] == "New Machines Labs"


def test_agent_schema_bounds_the_customer_copy():
    bundle = load_bundle(settings.defs_dir())
    finance = bundle.get("agent", "finance-agent")
    assert validate_bundle(bundle) == []
    for field, limit in (("name", 80), ("summary", 280), ("publisher_name", 80)):
        long = type(finance)(
            kind="agent",
            key="finance-agent",
            body={**finance.body, field: "x" * (limit + 1)},
            files=finance.files,
            path=finance.path,
        )
        items = {**bundle.items, ("agent", "finance-agent"): long}
        errors = validate_bundle(type(bundle)(items=items))
        assert any(field in str(e) for e in errors), field


def test_agent_schema_keeps_the_copy_optional():
    bundle = load_bundle(settings.defs_dir())
    finance = bundle.get("agent", "finance-agent")
    body = {k: v for k, v in finance.body.items() if k not in ("name", "summary", "publisher_name")}
    bare = type(finance)(kind="agent", key="finance-agent", body=body, files=finance.files, path=finance.path)
    items = {**bundle.items, ("agent", "finance-agent"): bare}
    assert validate_bundle(type(bundle)(items=items)) == []


# --- demo workspace (runtime off, definition files) -------------------------------------------------------


def test_demo_lists_definition_agents_first_then_samples(client):
    agents = client.get("/v1/agents").json()
    ids = [a["id"] for a in agents]
    assert ids[:3] == DEFINITION_AGENTS
    assert {a["source"] for a in agents[:3]} == {"definition"}
    assert agents[3:] and {a["source"] for a in agents[3:]} == {"sample"}
    assert "agent_shipping" in ids


def test_definition_agent_shape(client):
    finance = by_id(client.get("/v1/agents").json())["finance-agent"]
    assert finance["name"] == "Finance Agent"
    assert finance["publisher"] == "New Machines Labs"
    assert finance["summary"]
    assert finance["version"] == "1.0.0"
    assert finance["certified"] is True
    assert finance["capabilities"] == ["finance.reconcile"]
    assert finance["regions"] == ["asia-south1"]
    assert finance["skills"] == [
        {"key": "match-orders", "title": "Match orders"},
        {"key": "explain-mismatch", "title": "Explain mismatch"},
    ]
    assert finance["tools"] == []
    assert finance["modelProfile"] == "reasoning"
    # The invoice pack names the sample finance agent, which is folded into this one.
    assert finance["usedBy"] == [RECON, INVOICES]


def test_definition_agent_tools(client):
    retail = by_id(client.get("/v1/agents").json())["retail-agent"]
    assert retail["tools"] == ["shopify.list_orders"]
    assert retail["usedBy"] == [REFUNDS]


def test_samples_named_like_a_definition_agent_are_folded_into_it(client):
    agents = client.get("/v1/agents").json()
    names = [a["name"] for a in agents]
    assert len(names) == len(set(names))
    assert not {"agent_finance", "agent_ops", "agent_retail"} & {a["id"] for a in agents}
    # The fixture id still resolves, to the definition agent.
    folded = client.get("/v1/agents/agent_finance").json()
    assert (folded["id"], folded["source"]) == ("finance-agent", "definition")
    # Fixture packs name the definition agent instead.
    listed = {p["slug"]: p for p in client.get("/v1/workflow-packs").json()}
    assert listed["overdue-invoice-follow-up"]["agents"] == ["finance-agent"]
    assert listed["refund-triage"]["agents"] == ["retail-agent"]
    assert client.get("/v1/workflow-packs/weekly-inventory-report").json()["agents"] == ["ops-agent"]


def test_other_sample_agents_stay_samples_used_by_their_fixture_packs(client):
    shipping = by_id(client.get("/v1/agents").json())["agent_shipping"]
    assert shipping["source"] == "sample"
    assert shipping["skills"] == [] and shipping["tools"] == []
    assert "modelProfile" not in shipping
    assert [p["slug"] for p in shipping["usedBy"]] == ["shipping-exceptions"]
    assert client.get("/v1/workflow-packs/shipping-exceptions").json()["agents"] == ["agent_shipping"]


def test_get_one_agent(client):
    r = client.get("/v1/agents/ops-agent")
    assert r.status_code == 200
    assert r.json()["usedBy"] == [RECON, INVENTORY]
    assert client.get("/v1/agents/agent_shipping").json()["source"] == "sample"


def test_unknown_agent_is_404_problem(client):
    r = client.get("/v1/agents/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "NOT_FOUND"


def test_fixture_pack_with_a_definition_uses_its_agents_and_connectors(client):
    pack = client.get(f"/v1/workflow-packs/{PACK}").json()
    assert pack["agents"] == ["finance-agent", "ops-agent"]
    assert [(c["app"], c["access"]) for c in pack["connectors"]] == [
        ("Shopify", "read"),
        ("Stripe", "read"),
        ("Google Sheets", "write (approval)"),
    ]
    # The default connector mode is sandbox, so every connector is a labelled mock.
    assert all(c["mocked"] is True for c in pack["connectors"])
    listed = {p["slug"]: p for p in client.get("/v1/workflow-packs").json()}
    assert listed[PACK]["agents"] == ["finance-agent", "ops-agent"]
    # A pack without a definition keeps its own connectors.
    assert [c["app"] for c in listed["refund-triage"]["connectors"]] == ["Shopify", "Gmail"]


def test_live_connector_mode_is_never_mocked(client, monkeypatch):
    monkeypatch.setenv("NM_CONNECTOR_MODE", "live")
    pack = client.get(f"/v1/workflow-packs/{PACK}").json()
    assert [c["mocked"] for c in pack["connectors"]] == [False, False, False]


def test_auto_connector_mode_labels_unconnected_connectors_once_per_request(client, monkeypatch):
    checked: list[str] = []

    class FakeComposio(drivers.ComposioDriver):
        def is_connected(self, toolkit: str) -> bool:
            checked.append(toolkit)
            return toolkit == "stripe"

    monkeypatch.setattr(drivers, "ComposioDriver", FakeComposio)
    monkeypatch.setenv("NM_CONNECTOR_MODE", "auto")
    pack = client.get(f"/v1/workflow-packs/{PACK}").json()
    assert [(c["app"], c["mocked"]) for c in pack["connectors"]] == [
        ("Shopify", True),
        ("Stripe", False),
        ("Google Sheets", True),
    ]
    assert sorted(checked) == ["googlesheets", "shopify", "stripe"]


def test_auto_connector_mode_falls_back_to_sandbox_when_composio_fails(client, monkeypatch):
    class BrokenComposio(drivers.ComposioDriver):
        def is_connected(self, toolkit: str) -> bool:
            raise RuntimeError("DEMO_USER_UID is not set")

    monkeypatch.setattr(drivers, "ComposioDriver", BrokenComposio)
    monkeypatch.setenv("NM_CONNECTOR_MODE", "auto")
    pack = client.get(f"/v1/workflow-packs/{PACK}").json()
    assert all(c["mocked"] is True for c in pack["connectors"])


# --- live workspace ---------------------------------------------------------------------------------------


@pytest.fixture
def live(monkeypatch) -> TestClient:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    reset_store()
    return TestClient(create_app())


def test_live_lists_definition_agents_only(live):
    agents = live.get("/v1/agents").json()
    assert [a["id"] for a in agents] == DEFINITION_AGENTS
    assert {a["source"] for a in agents} == {"definition"}
    assert live.get("/v1/agents/agent_finance").status_code == 404
    assert live.get("/v1/agents/finance-agent").json()["usedBy"] == [RECON]


@pytest.fixture
def live_runtime(db, monkeypatch) -> TestClient:
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    monkeypatch.setattr(temporal_client, "start_run", lambda *a, **k: None)
    reset_store()
    return TestClient(create_app())


def test_live_reads_published_agents_from_the_registry(live_runtime, db):
    finance = load_bundle(settings.defs_dir()).get("agent", "finance-agent")
    edited = type(finance)(
        kind="agent",
        key="finance-agent",
        body={**finance.body, "name": "Ledger Agent", "summary": "Edited in the console."},
        files={**finance.files, "skills/match-orders.md": "---\nname: m\n---\n\n# Pair every order\n"},
        path=finance.path,
    )
    registry.publish(db, edited, "ops@newmachin.es", "Rename")
    db.commit()
    agents = by_id(live_runtime.get("/v1/agents").json())
    assert set(agents) == set(DEFINITION_AGENTS)
    assert agents["finance-agent"]["name"] == "Ledger Agent"
    assert agents["finance-agent"]["summary"] == "Edited in the console."
    assert agents["finance-agent"]["skills"][0] == {"key": "match-orders", "title": "Pair every order"}
    assert [p["slug"] for p in agents["ops-agent"]["usedBy"]] == [PACK]
