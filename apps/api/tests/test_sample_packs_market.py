# ruff: noqa: F811  (fixtures are imported from test_live_catalog and then named as arguments)
"""The four sample packs in a live workspace: listed with their categories and Google connectors, added,
connected in sandbox and started by one org, invisible to another."""

import pytest

from tests.test_live_catalog import As, ana, ben, live, starts  # noqa: F401

SAMPLE_PACKS = {
    "inbox-lead-tracker": {
        "name": "Inbox Lead Tracker",
        "category": "Sales operations",
        "agents": ["lead-agent"],
        "apps": ["gmail", "googlesheets"],
        "input": {"spreadsheet_id": "sandbox-leads-sheet-000000000000001"},
    },
    "support-inbox-triage": {
        "name": "Support Inbox Triage",
        "category": "Customer operations",
        "agents": ["support-agent", "writer-agent"],
        "apps": ["gmail", "googlesheets"],
        "input": {"spreadsheet_id": "sandbox-support-cases-sheet-0000001"},
    },
    "weekly-expense-check": {
        "name": "Weekly Expense Check",
        "category": "Finance operations",
        "agents": ["expense-agent", "writer-agent"],
        "apps": ["googlesheets", "gmail"],
        "input": {
            "week_start": "2026-10-05",
            "spreadsheet_id": "sandbox-expenses-sheet-0000000000001",
            "expenses_range": "Expenses!A:E",
            "summary_tab": "Summary",
            "email_to": "finance@yourco.example.com",
        },
    },
    "meeting-follow-ups": {
        "name": "Meeting Follow-ups",
        "category": "Operations",
        "agents": ["meeting-agent", "writer-agent"],
        "apps": ["googlecalendar", "gmail"],
        "input": {"day": "2026-10-15", "signature": "Alex Tan"},
    },
}
APP_NAMES = {"gmail": "Gmail", "googlesheets": "Google Sheets", "googlecalendar": "Google Calendar"}
CAP_MINOR, BUDGET_MINOR = 2500, 1000


def test_the_marketplace_lists_the_sample_packs_with_google_connectors_only(ana):
    packs = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}
    for slug, want in SAMPLE_PACKS.items():
        pack = packs[slug]
        assert (pack["name"], pack["category"], pack["agents"]) == (
            want["name"],
            want["category"],
            want["agents"],
        )
        assert [c["app"] for c in pack["connectors"]] == [APP_NAMES[a] for a in want["apps"]]
        assert all(c["mocked"] for c in pack["connectors"])  # sandbox mode: labelled as simulated
        assert pack["installed"] is False and pack["publisher"] == "New Machines Labs"
    lead = packs["inbox-lead-tracker"]
    assert [(c["app"], c["access"]) for c in lead["connectors"]] == [
        ("Gmail", "read"),  # access is per pack: it only lists mail, though the connector can send
        ("Google Sheets", "write (approval)"),
    ]
    support = packs["support-inbox-triage"]
    assert [(c["app"], c["access"]) for c in support["connectors"]] == [
        ("Gmail", "write (approval)"),  # it saves reply drafts
        ("Google Sheets", "write (approval)"),
    ]
    meetings = packs["meeting-follow-ups"]
    assert [(c["app"], c["access"]) for c in meetings["connectors"]] == [
        ("Google Calendar", "read"),
        ("Gmail", "write (approval)"),
    ]


def test_access_follows_the_capabilities_the_pack_contract_grants():
    from app.catalog.packs import connector_access

    gmail = {
        "tools": [
            {"id": "list_threads", "action_class": "read", "capability": "mail.read"},
            {"id": "send_email", "action_class": "write", "capability": "mail.send"},
        ],
        "defaults": {"read": "permit", "write": "require_approval"},
    }

    def grants(*caps):
        return {"authorization": {"tool_capabilities": list(caps)}}

    assert connector_access(gmail) == "write (approval)"  # no contract: the whole connector
    assert connector_access(gmail, grants("mail.read", "sheets.write")) == "read"
    assert connector_access(gmail, grants("mail.read", "mail.send")) == "write (approval)"  # agents may send


def test_each_sample_pack_has_its_input_schema_defaults(ana):
    for slug, want in SAMPLE_PACKS.items():
        detail = ana.get(f"/v1/workflow-packs/{slug}").json()
        assert set(want["input"]) <= set(detail["inputSchema"]["properties"]), slug
        assert set(detail["inputSchema"]["required"]) <= set(want["input"]), slug


@pytest.mark.parametrize("slug", sorted(SAMPLE_PACKS))
def test_a_sample_pack_is_added_connected_in_sandbox_and_started(slug, ana, ben, starts):
    want = SAMPLE_PACKS[slug]
    added = ana.post(
        f"/v1/organizations/{ana.org_id}/agent-installations",
        json={"packSlug": slug, "capMinor": CAP_MINOR, "reviewerPool": "team_then_network"},
    )
    assert added.status_code == 201, added.text
    for app in want["apps"]:
        connected = ana.connect(app)
        assert connected.status_code == 200, connected.text
        assert connected.json()["status"] == "sandbox"
    res = ana.start(packSlug=slug, input=want["input"], budgetMinor=BUDGET_MINOR)
    assert res.status_code == 202, res.json()
    run_id = res.json()["id"]
    started_org, started_input = starts.calls[-1][1:]
    assert started_org == ana.org_id
    assert want["input"].items() <= started_input.items()  # the pack's own defaults are added around it
    assert [r["id"] for r in ana.get("/v1/workflow-runs").json()] == [run_id]
    assert ben.get("/v1/workflow-runs").json() == []
    assert ben.get(f"/v1/workflow-runs/{run_id}").status_code == 404
    assert next(p for p in ben.get("/v1/workflow-packs").json() if p["slug"] == slug)["installed"] is False


def test_a_sample_pack_cannot_start_before_its_google_apps_are_connected(ana):
    slug = "meeting-follow-ups"
    body = {"packSlug": slug, "capMinor": CAP_MINOR, "reviewerPool": "team_then_network"}
    assert ana.post(f"/v1/organizations/{ana.org_id}/agent-installations", json=body).status_code == 201
    res = ana.start(packSlug=slug, input=SAMPLE_PACKS[slug]["input"], budgetMinor=BUDGET_MINOR)
    assert res.status_code >= 400 and res.status_code != 500


def test_read_only_packs_show_and_grant_read_only_access_on_every_connector():
    """F-14: a connector that can write (Gmail) shows read for a pack whose contract only authorizes its
    read tools, in the marketplace label and in the grants an install writes, for every platform pack."""
    from app import live_connections, settings
    from app.catalog.packs import connector_access
    from app.defs.loader import load_bundle

    bundle = load_bundle(settings.defs_dir())
    contracts = {d.key: d.body for d in bundle.of("contract")}
    connectors = {d.key: d.body for d in bundle.of("connector")}
    read_only = 0
    for pack in bundle.of("pack"):
        contract = contracts[pack.body["contract"]]
        granted = set(contract["authorization"]["tool_capabilities"])
        caps = live_connections.contract_capabilities(pack.body, contracts)
        for key in pack.body["connectors"]:
            tools = [t for t in connectors[key]["tools"] if t["capability"] in granted]
            if not tools or any(t["action_class"] != "read" for t in tools):
                continue
            read_only += 1
            grants = live_connections.pack_grants(connectors[key], "x", caps)
            assert connector_access(connectors[key], contract) == "read", (pack.key, key)
            assert grants and {g["access"] for g in grants} == {"read"}, (pack.key, key)
    assert read_only >= 5
    lead = bundle.get("pack", "inbox-lead-tracker").body
    assert connector_access(connectors["gmail"], contracts[lead["contract"]]) == "read"
