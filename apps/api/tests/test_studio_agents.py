"""Sub-project C, part 6: the Studio's palette and agents. Live workspace only; every route is checked across
orgs."""

from app.defs import owners
from tests.team_seed import TEAM_AGENT
from tests.test_live_catalog import As, ana, ben, live, starts  # noqa: F401


def _base(user: As, org_id: str | None = None) -> str:
    return f"/v1/organizations/{org_id or user.org_id}/studio"


def _draft(**changes) -> dict:
    return TEAM_AGENT.model_copy(update=changes).model_dump(by_alias=True, exclude_none=True)


def test_the_palette_lists_agents_tools_memory_and_result_shapes(ana):  # noqa: F811
    res = ana.get(f"{_base(ana)}/palette")
    assert res.status_code == 200, res.text
    palette = res.json()
    tools = {t["ref"]: t for t in palette["tools"]}
    assert (
        tools["gmail.create_draft"]["actionClass"] == "write"
        and tools["stripe.list_invoices"]["app"] == "Stripe"
    )
    assert tools["stripe.list_invoices"]["name"] == "List invoices"
    agents = {a["key"]: a for a in palette["agents"]}
    assert agents["writer-agent"]["outputSchema"]["title"] == "Email drafts"
    assert "builtByTeam" not in agents["writer-agent"]
    assert {s["key"] for s in palette["spaces"]} == {
        "customer-accounts",
        "expense-policy",
        "o2c-policy",
        "retail-commerce",
        "support-policies",
    }
    assert {"shared/agent-result", "shared/drafts", "shared/review-items"} <= {
        s["key"] for s in palette["schemas"]
    }
    assert all(s["key"].startswith("shared/") for s in palette["schemas"])


def test_an_agent_is_created_read_and_saved_as_new_versions(ana):  # noqa: F811
    res = ana.post(f"{_base(ana)}/agents", json=_draft())
    assert res.status_code == 201, res.text
    key = owners.org_key(ana.org_id, "invoice-helper")
    assert res.json()["key"] == key and res.json()["version"] == 1
    assert ana.get(f"{_base(ana)}/agents/{key}").json()["draft"] == _draft()
    palette_agents = {a["key"]: a for a in ana.get(f"{_base(ana)}/palette").json()["agents"]}
    assert (
        palette_agents[key]["builtByTeam"] is True
        and palette_agents[key]["outputSchemaRef"] == "shared/agent-result"
    )
    same = ana.post(f"{_base(ana)}/agents/{key}", json={"draft": _draft(), "baseVersion": 1})
    assert same.status_code == 200 and same.json()["version"] == 1  # nothing changed, nothing published
    edited = ana.post(
        f"{_base(ana)}/agents/{key}", json={"draft": _draft(summary="Plans nudges."), "baseVersion": 1}
    )
    assert edited.json()["version"] == 2 and edited.json()["draft"]["summary"] == "Plans nudges."
    stale = ana.post(f"{_base(ana)}/agents/{key}", json={"draft": _draft(summary="Older."), "baseVersion": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    [listed] = ana.get(f"{_base(ana)}/agents").json()
    assert (listed["key"], listed["version"], listed["modelProfile"], listed["usedBy"]) == (
        key,
        2,
        "fast",
        [],
    )
    catalog = {a["id"]: a for a in ana.get("/v1/agents").json()}
    assert catalog[key]["builtByTeam"] is True and catalog[key]["name"] == "Invoice helper"


def test_a_second_agent_with_the_same_name_gets_its_own_key(ana):  # noqa: F811
    assert ana.post(f"{_base(ana)}/agents", json=_draft()).status_code == 201
    second = ana.post(f"{_base(ana)}/agents", json=_draft())
    assert second.json()["key"] == owners.org_key(ana.org_id, "invoice-helper-2")


def test_an_agent_that_writes_is_refused_with_its_issue(ana):  # noqa: F811
    check = ana.post(f"{_base(ana)}/agents:validate", json=_draft(tools=["gmail.create_draft"]))
    assert check.status_code == 200 and check.json()["ok"] is False
    assert check.json()["issues"][0]["path"] == "tools[0]"
    assert ana.post(f"{_base(ana)}/agents:validate", json=_draft()).json() == {"ok": True, "issues": []}
    res = ana.post(f"{_base(ana)}/agents", json=_draft(tools=["gmail.create_draft"]))
    assert res.status_code == 422 and res.json()["code"] == "INVALID_DEFINITION"
    assert (
        res.json()["errors"][0]["path"] == "tools[0]"
        and "may only read" in res.json()["errors"][0]["message"]
    )
    assert ana.get(f"{_base(ana)}/agents").json() == []


def test_another_org_never_sees_or_changes_an_orgs_agents(ana, ben):  # noqa: F811
    key = ana.post(f"{_base(ana)}/agents", json=_draft()).json()["key"]
    assert ben.get(_base(ben, ana.org_id) + "/agents").status_code == 403
    theirs = ben.post(_base(ben, ana.org_id) + "/agents", json=_draft())
    assert (theirs.status_code, theirs.json()["code"]) == (403, "TENANT_SCOPE_DENIED")
    assert [a["key"] for a in ana.get(f"{_base(ana)}/agents").json()] == [key]
    assert ben.get(f"{_base(ben)}/agents").json() == []
    assert ben.get(f"{_base(ben)}/agents/{key}").status_code == 404
    assert ben.post(f"{_base(ben)}/agents/{key}", json={"draft": _draft()}).status_code == 404
    assert key not in {a["key"] for a in ben.get(f"{_base(ben)}/palette").json()["agents"]}
    assert key not in {a["id"] for a in ben.get("/v1/agents").json()}


def test_a_reviewer_cannot_build(db, ana):  # noqa: F811
    db.execute("UPDATE org_members SET role = 'reviewer' WHERE user_id = 'uid_ana'")
    db.commit()
    res = ana.post(f"{_base(ana)}/agents", json=_draft())
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"
    assert ana.get(f"{_base(ana)}/palette").status_code == 200  # reading is fine


def test_the_studio_is_not_in_the_demo_workspace(client):
    res = client.get("/v1/organizations/org_hp01/studio/palette")
    assert res.status_code == 404 and res.json()["detail"] == "The Studio is part of the live workspace."
