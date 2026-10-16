"""Final API review fixes: another workspace's listings never block or leak into a workspace's own Studio
(pack names, imported decision rules), the added-pack suggestion knows its held version, and the check pack's
key is reserved."""

from app import listing_checks
from app.defs import owners, registry
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list, defs_of
from tests.team_seed import _own, clone_pack
from tests.test_listed_marketplace import _list
from tests.test_live_catalog import ana, ben, live, starts  # noqa: F401
from tests.test_studio_packs import _agent, _agent_body, _base, _create, _draft

PACK = "order-payment-reconciliation"
SUGGEST = "/v1/workflow-packs:suggest"


def test_another_workspaces_listed_pack_name_never_blocks_a_save(ana, ben, db):  # noqa: F811
    key, draft = _create(ben)
    add_publisher(db, ana.org_id, "Acme Labs")
    theirs = clone_pack(db, PACK, ana.org_id, "nudges", title=draft["name"])
    _list(db, ana.org_id, "pack", theirs, 1, 100)
    changed = {**draft, "description": "Reworded."}
    saved = ben.post(f"{_base(ben)}/packs/{key}", json={"draft": changed, "baseVersion": 1})
    assert saved.status_code == 200, saved.text
    agent = owners.org_key(ben.org_id, "invoice-helper")
    body = {"draft": _agent_body(summary="New."), "baseVersion": 1}
    more = ben.post(f"{_base(ben)}/agents/{agent}", json=body)
    assert more.status_code == 200, more.text
    check = ben.post(f"{_base(ben)}/packs:validate", params={"key": key}, json=changed).json()
    assert check["ok"] is True


def test_an_import_inlines_only_own_or_platform_decision_rules(ana, ben, db):  # noqa: F811
    rules = owners.org_key(ana.org_id, "rules")
    platform = registry.latest(db, "decision_rules", "overdue-invoices").body
    _own(db, ana.org_id, "decision_rules", rules, platform)
    add_publisher(db, ana.org_id, "Acme Labs")
    pack = clone_pack(db, PACK, ana.org_id, "recon")
    listing = add_listing(db, "pack", pack, ana.org_id, name="Listed pack")
    refs = defs_of(db, [("pack", pack), ("workflow", pack), ("contract", pack), ("decision_rules", rules)])
    approve_and_list(db, listing, add_version(db, listing, 1, refs, price_minor=100))
    db.commit()
    text = (
        "kind: workflow\nkey: x\nentry_node_id: start\nnodes:\n"
        "  - {id: start, type: trigger, version: '1', config: {}, routes: {next: check}}\n"
        f"  - {{id: check, type: decision, version: '1', config: {{rules: {rules}}}, "
        "routes: {nothing: done, human_review: done}}\n"
        "  - {id: done, type: end, version: '1', config: {status: COMPLETED}}\n"
    )
    for user in (ben, ana):
        imported = user.post(f"{_base(user)}/workflow:import", json={"yaml": text}).json()
        check = imported["steps"][1]
        assert (check.get("rules") is not None) is (user is ana), user.org_id


def test_suggest_knows_the_version_an_added_listed_pack_holds(ana, ben, db):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    title = "Shopify orders payments reconciliation matcher"
    key = clone_pack(db, PACK, ana.org_id, "recon", title=title)
    _list(db, ana.org_id, "pack", key, 1, 100)
    hire = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(f"/v1/organizations/{ben.org_id}/agent-installations", json=hire).status_code == 201
    found = ben.post(SUGGEST, json={"text": title}).json()
    assert found["pack"]["slug"] == key
    assert found["pack"]["listing"]["updateAvailable"] is False


def test_a_studio_pack_called_listing_check_gets_another_key(ana):  # noqa: F811
    draft = _draft(_agent(ana), name="Listing check")
    res = ana.post(f"{_base(ana)}/packs", json=draft)
    assert res.status_code == 201, res.text
    assert res.json()["key"] != listing_checks.check_pack_key(ana.org_id)
