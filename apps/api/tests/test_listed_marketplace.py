"""Sub-project D, part 17: another workspace's listed pack and agent show in the marketplace, the agent
catalog and the Studio palette with publisher and fee; installs pin the approved version and update on
request. Drafts and unlisted items never show."""

import pytest

from app import fees, listings, live_catalog
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.errors import ApiProblem
from tests.live_seed import NOW, add_run
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list, defs_of
from tests.team_seed import TEAM_AGENT, clone_agent, clone_pack, invoice_nudges
from tests.test_live_catalog import _rows, ana, ben, live, starts  # noqa: F401

PACK = "order-payment-reconciliation"


def _bundle(db, kind: str, key: str) -> list[dict]:
    refs = [("pack", key), ("workflow", key), ("contract", key)] if kind == "pack" else [("agent", key)]
    return defs_of(db, refs)


def _list(db, org_id: str, kind: str, key: str, version: int, price: int, listing: str | None = None) -> str:
    listing = listing or add_listing(db, kind, key, org_id, name=f"Listed {kind}")
    approve_and_list(
        db, listing, add_version(db, listing, version, _bundle(db, kind, key), price_minor=price)
    )
    db.commit()
    return listing


def _republish(db, kind: str, key: str, name: str) -> None:
    v = registry.latest(db, kind, key)
    d = Definition(
        kind=kind, key=key, body={**v.body, "name": name}, files=dict(v.files), path=path_for(kind, key)
    )
    registry.publish(db, d, "test", "a later version", source=registry.BUILDER)
    db.commit()


def _packs(user) -> dict[str, dict]:
    return {p["slug"]: p for p in user.get("/v1/workflow-packs").json()}


def test_a_listed_pack_shows_with_its_publisher_and_fee(ana, ben, db):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    _list(db, ana.org_id, "pack", key, 1, 250)
    _republish(db, "pack", key, "Acme recon draft")
    seen = _packs(ben)[key]
    assert seen["name"] == "Acme recon" and seen["certified"] is False and seen["publisher"] == "Acme Labs"
    assert seen["listing"]["fee"]["amountMinor"] == 250 and seen["listing"]["feeUnit"] == "run"
    assert seen.get("priceNote") is None
    assert ben.get(f"/v1/workflow-packs/{key}").json()["listing"]["publisher"] == "Acme Labs"
    own = _packs(ana)[key]
    assert own["name"] == "Acme recon draft" and own.get("listing") is None and own["builtByTeam"] is True
    assert _packs(ben)[PACK].get("listing") is None  # the platform's packs are unchanged


def test_private_and_unlisted_packs_never_show(ana, ben, db):  # noqa: F811
    private = clone_pack(db, PACK, ana.org_id, "private")
    key = clone_pack(db, PACK, ana.org_id, "recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 0)
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    db.commit()
    assert private not in _packs(ben) and key not in _packs(ben)
    assert ben.get(f"/v1/workflow-packs/{private}").status_code == 404
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    for slug in (private, key):
        res = ben.post(install, json={"packSlug": slug, "capMinor": 2000, "reviewerPool": "team"})
        assert res.status_code == 404, res.text
    assert _rows(db, "SELECT 1 FROM installations WHERE org_id = %s", ben.org_id) == []


def test_install_pins_the_approved_version_and_update_moves_it(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 100)
    _republish(db, "pack", key, "Draft only")
    body = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(f"/v1/organizations/{ben.org_id}/agent-installations", json=body).status_code == 201
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ben.org_id)
    assert row["pack_version"] == 1
    upgrade = f"/v1/organizations/{ben.org_id}/agent-installations/{key}:upgrade"
    assert ben.post(upgrade).json()["code"] == "UP_TO_DATE"
    _list(db, ana.org_id, "pack", key, 2, 150, listing=listing)
    _republish(db, "pack", key, "Draft three")  # a newer draft after the approval: an update never pins it
    seen = _packs(ben)[key]["listing"]
    assert (seen["version"], seen["installedVersion"], seen["updateAvailable"]) == (2, 1, True)
    add_run(db, "run_9401", ben.org_id, NOW, status="RUNNING", pack=key)
    db.commit()
    assert ben.post(upgrade).json()["code"] == "RUNS_IN_PROGRESS"
    db.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = 'run_9401'")
    db.commit()
    res = ben.post(upgrade)
    assert res.status_code == 200, res.text
    assert res.json()["packSlug"] == key
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ben.org_id)
    assert row["pack_version"] == 2
    assert _packs(ben)[key]["listing"]["updateAvailable"] is False


def test_a_buyer_installs_and_runs_the_approved_version_never_a_newer_draft(ana, ben, db, starts):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    _list(db, ana.org_id, "pack", key, 1, 100)
    _republish(db, "pack", key, "Unapproved draft")  # the publisher's newer draft: never pinned
    body = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(f"/v1/organizations/{ben.org_id}/agent-installations", json=body).status_code == 201
    [row] = _rows(db, "SELECT pack_version FROM installations WHERE org_id = %s", ben.org_id)
    assert row["pack_version"] == 1
    for app in ("shopify", "stripe", "googlesheets"):
        assert ben.connect(app).status_code == 200
    res = ben.start(packSlug=key, budgetMinor=1500)
    assert res.status_code == 202, res.text
    [run] = _rows(db, "SELECT snapshot FROM runs WHERE org_id = %s AND pack_slug = %s", ben.org_id, key)
    pinned = {(v["kind"], v["key"]): v["version"] for v in run["snapshot"]["versions"]}
    assert pinned[("pack", key)] == 1
    assert run["snapshot"]["defs"]["pack"][key]["body"]["name"] == "Acme recon"


def _grants(db, org_id: str, app: str) -> set[tuple[str, str]]:
    [row] = _rows(db, "SELECT grants FROM connections WHERE org_id = %s AND app = %s", org_id, app)
    return {(g["install"], g["capability"]) for g in row["grants"]}


def _widen_contract(db, key: str, capability: str) -> None:
    v = registry.latest(db, "contract", key)
    auth = v.body["authorization"]
    body = {
        **v.body,
        "authorization": {**auth, "tool_capabilities": [*auth["tool_capabilities"], capability]},
    }
    d = Definition(kind="contract", key=key, body=body, files={}, path=path_for("contract", key))
    registry.publish(db, d, "test", "a wider contract", source=registry.BUILDER)
    db.commit()


def test_grants_follow_the_pinned_version_until_the_buyer_updates(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 100)
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    body = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(install, json=body).status_code == 201
    assert ben.connect("stripe").status_code == 200
    v1 = {("Acme recon", "payments.read")}
    assert _grants(db, ben.org_id, "stripe") == v1
    _widen_contract(db, key, "invoices.read")  # v2 renames the pack and may read invoices too
    _republish(db, "pack", key, "Acme recon v2")
    _list(db, ana.org_id, "pack", key, 2, 100, listing=listing)
    assert ben.connect("stripe").status_code == 200  # recomputed while still on v1
    assert _grants(db, ben.org_id, "stripe") == v1
    assert ben.post(install, json={**body, "capMinor": 2500}).status_code == 201  # settings saved on v1
    assert _grants(db, ben.org_id, "stripe") == v1
    [stripe] = [c for c in ben.get("/v1/connections").json() if c["app"] == "Stripe"]
    assert {(g["install"], g["capability"]) for g in stripe["grants"]} == v1
    assert ben.post(f"{install}/{key}:upgrade").status_code == 200
    v2 = {("Acme recon v2", "payments.read"), ("Acme recon v2", "invoices.read")}
    assert _grants(db, ben.org_id, "stripe") == v2
    assert ben.connect("stripe").status_code == 200
    assert _grants(db, ben.org_id, "stripe") == v2


def _own_schema(db, org_id: str, key: str, body: dict) -> None:
    registry.claim(db, "schema", key, owners.org_owner(org_id), "test")
    d = Definition(kind="schema", key=key, body=body, files={}, path=path_for("schema", key))
    registry.publish(db, d, "test", "a schema of the publisher's", source=registry.BUILDER)
    db.commit()


def test_a_pinned_install_shows_the_start_form_of_its_version(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 100)
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    assert (
        ben.post(install, json={"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}).status_code == 201
    )
    schema = f"{key.split('--')[0]}--recon-month"
    month = {"type": "object", "required": ["month"], "properties": {"month": {"type": "string"}}}
    _own_schema(db, ana.org_id, schema, month)
    contract = registry.latest(db, "contract", key)
    body = {**contract.body, "input_schema_ref": schema}
    d = Definition(kind="contract", key=key, body=body, files={}, path=path_for("contract", key))
    registry.publish(db, d, "test", "v2 takes a month", source=registry.BUILDER)
    db.commit()
    _republish(db, "pack", key, "Acme recon by month")
    refs = defs_of(db, [("pack", key), ("workflow", key), ("contract", key), ("schema", schema)])
    approve_and_list(db, listing, add_version(db, listing, 2, refs, price_minor=100))
    db.commit()
    detail = ben.get(f"/v1/workflow-packs/{key}").json()
    assert detail["listing"]["updateAvailable"] is True
    assert detail["inputSchema"]["required"] == ["since", "until", "spreadsheet_id"]  # v1's start form
    assert ana.get(f"/v1/workflow-packs/{key}").json()["inputSchema"]["required"] == ["month"]  # the newest
    assert ben.post(f"{install}/{key}:upgrade").status_code == 200
    assert ben.get(f"/v1/workflow-packs/{key}").json()["inputSchema"]["required"] == ["month"]


def _held(db, org_id: str) -> str:
    [row] = _rows(db, "SELECT listing_version_id FROM installations WHERE org_id = %s", org_id)
    return row["listing_version_id"]


def test_a_contract_only_re_approval_is_an_update(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon", title="Acme recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 100)
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    assert (
        ben.post(install, json={"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}).status_code == 201
    )
    assert ben.connect("stripe").status_code == 200
    v1 = {("Acme recon", "payments.read")}
    _widen_contract(db, key, "invoices.read")
    _list(db, ana.org_id, "pack", key, 1, 150, listing=listing)  # the same pack version, a wider contract
    assert ben.connect("stripe").status_code == 200
    assert _grants(db, ben.org_id, "stripe") == v1
    assert fees.pack_fee_minor(db, ben.org_id, key, 1, _held(db, ben.org_id)) == 100  # the held version's
    seen = _packs(ben)[key]["listing"]
    assert (seen["version"], seen["installedVersion"], seen["updateAvailable"]) == (1, 1, True)
    res = ben.post(f"{install}/{key}:upgrade")
    assert res.status_code == 200, res.text
    assert _grants(db, ben.org_id, "stripe") == v1 | {("Acme recon", "invoices.read")}
    [row] = _rows(
        db,
        "SELECT i.listing_version_id = l.current_version_id AS current FROM installations i "
        "JOIN listings l ON l.definition_key = i.pack_slug WHERE i.org_id = %s",
        ben.org_id,
    )
    assert row["current"] is True
    assert fees.pack_fee_minor(db, ben.org_id, key, 1, _held(db, ben.org_id)) == 150
    assert _packs(ben)[key]["listing"]["updateAvailable"] is False
    assert ben.post(f"{install}/{key}:upgrade").json()["code"] == "UP_TO_DATE"


def _conflict(res) -> None:
    assert (res.status_code, res.json()["code"]) == (409, "CONFLICT"), res.text
    assert "A pack you've added already uses the name" in res.json()["detail"]


def test_a_listed_pack_named_like_an_added_pack_is_refused(ana, ben, db):  # noqa: F811
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    hire = {"capMinor": 2000, "reviewerPool": "team"}
    mine = clone_pack(db, PACK, ben.org_id, "mine", title="Ben recon")
    same = clone_pack(db, PACK, ana.org_id, "same", title="ben RECON")
    _list(db, ana.org_id, "pack", same, 1, 0)
    platform = clone_pack(db, PACK, ana.org_id, "platform", title="Order & Payment Reconciliation")
    _list(db, ana.org_id, "pack", platform, 1, 0)
    # Packs Ben has not added hold no grants: a listed pack named like one is added freely.
    assert ben.post(install, json={**hire, "packSlug": platform}).status_code == 201
    db.execute("DELETE FROM installations WHERE org_id = %s", (ben.org_id,))
    db.commit()
    # Once Ben adds his own pack and the platform's, a listed pack of either name is refused.
    for slug in (mine, PACK):
        assert ben.post(install, json={**hire, "packSlug": slug}).status_code == 201
    for slug in (same, platform):
        _conflict(ben.post(install, json={**hire, "packSlug": slug}))
    other = clone_pack(db, PACK, ana.org_id, "other", title="Acme other")
    listing = _list(db, ana.org_id, "pack", other, 1, 0)
    assert ben.post(install, json={**hire, "packSlug": other}).status_code == 201
    _republish(db, "pack", other, "Ben recon")
    _list(db, ana.org_id, "pack", other, 2, 0, listing=listing)
    _conflict(ben.post(f"{install}/{other}:upgrade"))
    rows = _rows(db, "SELECT pack_slug, pack_version FROM installations WHERE org_id = %s", ben.org_id)
    assert {(r["pack_slug"], r["pack_version"]) for r in rows} == {(mine, 1), (PACK, 1), (other, 1)}


@pytest.mark.parametrize("first", [0, 1])
def test_two_publishers_may_list_one_name_and_a_buyer_adds_either(ana, ben, db, first):  # noqa: F811
    db.execute("INSERT INTO orgs (id, name) VALUES ('org_carl', 'Carl Co') ON CONFLICT DO NOTHING")
    keys = [
        clone_pack(db, PACK, org, "sync", title=title)
        for org, title in ((ana.org_id, "Invoice sync"), ("org_carl", "invoice SYNC"))
    ]
    _list(db, ana.org_id, "pack", keys[0], 1, 0)
    _list(db, "org_carl", "pack", keys[1], 1, 0)
    assert {keys[0], keys[1]} <= set(_packs(ben))
    install = f"/v1/organizations/{ben.org_id}/agent-installations"
    hire = {"capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(install, json={**hire, "packSlug": keys[first]}).status_code == 201
    _conflict(ben.post(install, json={**hire, "packSlug": keys[1 - first]}))
    rows = _rows(db, "SELECT pack_slug FROM installations WHERE org_id = %s", ben.org_id)
    assert [r["pack_slug"] for r in rows] == [keys[first]]


def test_a_listing_gone_mid_install_adds_nothing(ana, ben, db, monkeypatch):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    _list(db, ana.org_id, "pack", key, 1, 100)
    latest = registry.visible_version(db, "pack", key, ben.org_id)
    # The listing went between the pack read and the pin: no listed pack is added without its listing version.
    monkeypatch.setattr(listings, "market_info", lambda conn, org_id: {})
    with pytest.raises(ApiProblem) as refused:
        live_catalog._first_pin(db, ben.org_id, latest, key)
    assert (refused.value.status, refused.value.code) == (404, "NOT_FOUND")
    own = registry.visible_version(db, "pack", PACK, ben.org_id)
    assert live_catalog._first_pin(db, ben.org_id, own, PACK) == (own, None)  # the platform's: no listing


def test_saving_an_installs_settings_keeps_its_pinned_version(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    listing = _list(db, ana.org_id, "pack", key, 1, 100)
    base = f"/v1/organizations/{ben.org_id}/agent-installations"
    assert ben.post(base, json={"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}).status_code == 201
    _republish(db, "pack", key, "Version two")
    _list(db, ana.org_id, "pack", key, 2, 100, listing=listing)
    assert ben.post(base, json={"packSlug": key, "capMinor": 3000, "reviewerPool": "team"}).status_code == 201
    [row] = _rows(db, "SELECT pack_version, cap_minor FROM installations WHERE org_id = %s", ben.org_id)
    assert (row["pack_version"], row["cap_minor"]) == (1, 3000)


def test_update_refusals(ana, ben, db):  # noqa: F811
    key = clone_pack(db, PACK, ana.org_id, "recon")
    _list(db, ana.org_id, "pack", key, 1, 100)
    base = f"/v1/organizations/{ben.org_id}/agent-installations"
    assert ben.post(f"{base}/{key}:upgrade").json()["code"] == "PACK_NOT_HIRED"
    hire = {"packSlug": PACK, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(base, json=hire).status_code == 201
    assert ben.post(f"{base}/{PACK}:upgrade").json()["code"] == "NOT_LISTED"
    assert ben.post(f"{base}/nothing-here:upgrade").status_code == 404
    other = f"/v1/organizations/{ana.org_id}/agent-installations/{key}:upgrade"
    assert ben.post(other).json()["code"] == "TENANT_SCOPE_DENIED"
    own = f"/v1/organizations/{ana.org_id}/agent-installations"
    assert ana.post(own, json={**hire, "packSlug": key}).status_code == 201
    assert ana.post(f"{own}/{key}:upgrade").json()["code"] == "NOT_LISTED"  # its own listing has no updates


def test_a_listed_agent_shows_in_the_catalog_and_the_palette(ana, ben, db):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    agent = clone_agent(db, "finance-agent", ana.org_id, "matcher", title="Matcher")
    secret = clone_agent(db, "finance-agent", ana.org_id, "secret")
    listing = _list(db, ana.org_id, "agent", agent, 1, 30)
    agents = {a["id"]: a for a in ben.get("/v1/agents").json()}
    assert (
        agents[agent]["listing"]["feeUnit"] == "call" and agents[agent]["listing"]["publisher"] == "Acme Labs"
    )
    assert agents[agent]["certified"] is False and agents[agent]["publisher"] == "Acme Labs"
    assert secret not in agents
    assert agents["finance-agent"].get("listing") is None and agents["finance-agent"]["certified"] is True
    palette = ben.get(f"/v1/organizations/{ben.org_id}/studio/palette").json()["agents"]
    listed = {a["key"]: a for a in palette if a.get("listing")}
    assert set(listed) == {agent} and listed[agent]["listing"]["fee"]["amountMinor"] == 30
    assert secret not in {a["key"] for a in palette}
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    db.commit()
    palette = ben.get(f"/v1/organizations/{ben.org_id}/studio/palette").json()["agents"]
    assert agent not in {a["key"] for a in palette}


def test_a_pack_draft_may_use_a_listed_agent_until_it_is_withdrawn(ana, ben, db):  # noqa: F811
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/agents", json=TEAM_AGENT.model_dump(by_alias=True))
    assert res.status_code == 201, res.text
    agent = res.json()["key"]
    listing = _list(db, ana.org_id, "agent", agent, 1, 30)
    studio = f"/v1/organizations/{ben.org_id}/studio"
    draft = invoice_nudges(agent).model_dump(by_alias=True, exclude_none=True)
    saved = ben.post(f"{studio}/packs", json=draft)
    assert saved.status_code == 201, saved.text
    key = saved.json()["key"]
    db.execute("UPDATE listings SET status = 'unlisted' WHERE id = %s", (listing,))
    db.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    db.commit()
    check = ben.post(f"{studio}/packs:validate", params={"key": key}, json=draft).json()
    assert check["ok"] is False and [i["step"] for i in check["issues"]] == ["plan"]
    refused = ben.post(f"{studio}/packs/{key}", json={"draft": draft, "baseVersion": 1})
    assert refused.status_code == 422 and refused.json()["code"] == "INVALID_DEFINITION"


def test_another_publishers_listed_spaces_and_schemas_are_not_built_with(ana, ben, db):  # noqa: F811
    agent = clone_agent(db, "finance-agent", ana.org_id, "matcher")
    schema_key = f"{agent.split('--')[0]}--result"
    registry.claim(db, "schema", schema_key, owners.org_owner(ana.org_id), "test")
    body = {"type": "object", "title": "Acme result", "properties": {}}
    registry.publish(
        db,
        Definition(kind="schema", key=schema_key, body=body, files={}, path=path_for("schema", schema_key)),
        "test",
        "a schema of ana's",
        source=registry.BUILDER,
    )
    db.commit()
    listing = add_listing(db, "agent", agent, ana.org_id)
    refs = defs_of(db, [("agent", agent), ("schema", schema_key)])
    approve_and_list(db, listing, add_version(db, listing, 1, refs, price_minor=0))
    db.commit()
    palette = ben.get(f"/v1/organizations/{ben.org_id}/studio/palette").json()
    assert schema_key not in {s["key"] for s in palette["schemas"]}
    draft = invoice_nudges("writer-agent").model_dump(by_alias=True, exclude_none=True)
    draft["steps"][8]["config"]["schema"] = schema_key  # the verify step checks against ana's schema
    check = ben.post(f"/v1/organizations/{ben.org_id}/studio/packs:validate", json=draft).json()
    assert check["ok"] is False and "verify" in {i.get("step") for i in check["issues"]}
