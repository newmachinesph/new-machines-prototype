"""Studio pack copies: a platform or own pack opens as an unsaved draft the org can save as its own."""

from copy import deepcopy
from dataclasses import replace

import pytest

from app import db, settings
from app import studio_build as build
from app.defs import owners, registry
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list, defs_of
from tests.team_seed import TEAM_AGENT, clone_pack, invoice_nudges
from tests.test_live_catalog import As, ana, ben, live, starts  # noqa: F401

# Every pack in the platform catalog, so a new pack is never missed.
PLATFORM_PACKS = sorted(p.parent.name for p in (settings.defs_dir() / "packs").glob("*/pack.yaml"))
assert PLATFORM_PACKS


def _base(user: As) -> str:
    return f"/v1/organizations/{user.org_id}/studio"


def _copy(user: As, source: str):
    return user.post(f"{_base(user)}/packs:copy", json={"source": source})


def _versions() -> tuple[int, int]:
    """Rows of definition_versions and definition_owners: what a save would add to."""
    with db.connect() as conn:
        versions = conn.execute("SELECT count(*) AS n FROM definition_versions").fetchone()["n"]
        owned = conn.execute("SELECT count(*) AS n FROM definition_owners").fetchone()["n"]
    return versions, owned


def _own_draft(user: As) -> dict:
    agent = user.post(f"{_base(user)}/agents", json=TEAM_AGENT.model_dump(by_alias=True, exclude_none=True))
    return invoice_nudges(agent.json()["key"]).model_dump(by_alias=True, exclude_none=True)


@pytest.mark.parametrize("slug", PLATFORM_PACKS)
def test_every_platform_pack_copies_to_a_draft_the_studio_accepts(ana, slug):  # noqa: F811
    res = _copy(ana, slug)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["issues"] == []
    assert body["source"]["key"] == slug and body["draft"]["name"].endswith("(copy)")
    check = ana.post(f"{_base(ana)}/packs:validate", json=body["draft"]).json()
    assert check == {"ok": True, "issues": []}, check


def test_copying_saves_nothing_and_saving_the_copy_makes_an_own_pack(ana):  # noqa: F811
    before = _versions()
    draft = _copy(ana, "refund-triage").json()["draft"]
    assert _versions() == before
    saved = ana.post(f"{_base(ana)}/packs", json=draft)
    assert saved.status_code == 201, saved.text
    assert saved.json()["draft"]["steps"] == draft["steps"]
    [listed] = ana.get(f"{_base(ana)}/packs").json()
    assert listed["name"] == "Refund Triage (copy)"


def test_the_next_copy_gets_a_number(ana):  # noqa: F811
    first = _copy(ana, "refund-triage").json()["draft"]
    assert ana.post(f"{_base(ana)}/packs", json=first).status_code == 201
    assert _copy(ana, "refund-triage").json()["draft"]["name"] == "Refund Triage (copy 2)"


def test_an_own_pack_copies_with_its_steps(ana):  # noqa: F811
    draft = _own_draft(ana)
    key = ana.post(f"{_base(ana)}/packs", json=draft).json()["key"]
    copy = _copy(ana, key).json()
    assert copy["draft"]["steps"] == draft["steps"] and copy["draft"]["name"] == "Invoice nudges (copy)"
    assert copy["source"] == {"key": key, "name": "Invoice nudges", "version": 1}


def test_another_orgs_pack_is_not_found_and_an_unknown_key_too(ana, ben):  # noqa: F811
    key = ben.post(f"{_base(ben)}/packs", json=_own_draft(ben)).json()["key"]
    assert _copy(ana, key).status_code == 404
    assert _copy(ana, "no-such-pack").status_code == 404


def test_a_pack_another_publisher_lists_can_be_added_not_copied(ana, monkeypatch):  # noqa: F811
    # copy_pack reads registry.owner_of at call time; a developer-owned pack stands in for a listed one.
    monkeypatch.setattr(registry, "owner_of", lambda conn, kind, key: owners.Owner("developer", "pub_1"))
    res = _copy(ana, "refund-triage")
    assert res.status_code == 409 and res.json()["code"] == "NOT_COPYABLE"
    assert "added, not copied" in res.json()["detail"]


def test_copy_names_fit_and_count_up():
    from app.studio import copy_name

    assert copy_name("Refund Triage", set()) == "Refund Triage (copy)"
    assert copy_name("Refund Triage", {"refund triage (copy)"}) == "Refund Triage (copy 2)"
    long = copy_name("x" * 80, set())
    assert len(long) == 80 and long.endswith(" (copy)")


def test_the_catalog_marks_platform_and_own_packs_copyable(ana):  # noqa: F811
    ana.post(f"{_base(ana)}/packs", json=_own_draft(ana))
    packs = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}
    assert packs["refund-triage"]["copyable"] is True
    own = [p for slug, p in packs.items() if owners.is_reserved(slug)]
    assert own and all(p["copyable"] is True for p in own)


def test_a_pack_another_org_listed_is_not_marked_copyable(ana, ben, db):  # noqa: F811
    add_publisher(db, ben.org_id, "Ben Labs")
    key = clone_pack(db, "order-payment-reconciliation", ben.org_id, "recon", title="Ben recon")
    listing = add_listing(db, "pack", key, ben.org_id, name="Listed pack")
    refs = [("pack", key), ("workflow", key), ("contract", key)]
    approve_and_list(db, listing, add_version(db, listing, 1, defs_of(db, refs), price_minor=100))
    db.commit()
    seen = {p["slug"]: p for p in ana.get("/v1/workflow-packs").json()}[key]
    assert seen["listing"] and seen.get("copyable") is None


def test_a_reviewer_cannot_copy(ana, db):  # noqa: F811
    db.execute("UPDATE org_members SET role = 'reviewer' WHERE user_id = 'uid_ana'")
    db.commit()
    res = _copy(ana, "refund-triage")
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"


def _screen(draft: dict) -> dict:
    return next(s for s in draft["steps"] if s["type"] == "decision")


def test_a_copied_decision_keeps_its_model_setup_and_error_route(ana, db):  # noqa: F811
    platform = registry.latest(db, "decision_rules", "support-screen").body
    draft = _copy(ana, "support-inbox-triage").json()["draft"]
    screen = _screen(draft)
    assert screen["rules"]["evaluator"] == platform["evaluator"]
    assert screen["routes"]["unsorted"] == "triage"
    saved = ana.post(f"{_base(ana)}/packs", json=draft)
    assert saved.status_code == 201, saved.text
    key = saved.json()["key"]
    db.commit()
    rules = registry.latest(db, "decision_rules", build.rules_key(key, screen["id"]))
    assert rules.body["evaluator"] == platform["evaluator"]
    assert _screen(saved.json()["draft"])["rules"]["evaluator"] == platform["evaluator"]
    # An own pack that came from a copy copies again, its decision intact.
    again = _copy(ana, key).json()
    assert again["issues"] == [] and _screen(again["draft"])["rules"]["evaluator"] == platform["evaluator"]


def test_a_made_up_or_edited_model_setup_is_refused(ana):  # noqa: F811
    draft = _copy(ana, "support-inbox-triage").json()["draft"]
    screen = _screen(draft)
    screen["rules"]["evaluator"] = {**screen["rules"]["evaluator"], "keep": "true"}
    check = ana.post(f"{_base(ana)}/packs:validate", json=draft).json()
    assert check["ok"] is False
    [issue] = check["issues"]
    assert issue["step"] == screen["id"] and "decision model setup" in issue["message"]
    assert ana.post(f"{_base(ana)}/packs", json=draft).status_code == 422


def test_saving_an_own_pack_with_an_edited_model_setup_is_refused_too(ana):  # noqa: F811
    draft = _copy(ana, "support-inbox-triage").json()["draft"]
    key = ana.post(f"{_base(ana)}/packs", json=draft).json()["key"]
    saved = ana.get(f"{_base(ana)}/packs/{key}").json()["draft"]
    screen = _screen(saved)
    screen["rules"]["evaluator"] = {**screen["rules"]["evaluator"], "keep": "true"}
    res = ana.post(f"{_base(ana)}/packs/{key}", json={"draft": saved})
    assert res.status_code == 422, res.text
    assert "decision model setup" in res.text


def _republish(db, kind: str, key: str, change) -> None:
    """Publish a new version of a platform definition, as the Ops console does; `change` edits its body."""
    current = registry.latest(db, kind, key)
    body = change(deepcopy(current.body))
    registry.publish(db, replace(current, body=body), "ops@newmachin.es", "test edit")
    db.commit()


def _schema_key(db, pack_key: str) -> str:
    pack = registry.latest(db, "pack", pack_key).body
    workflow = registry.latest(db, "workflow", pack["workflow"]).body
    contract = registry.latest(db, "contract", workflow.get("work_contract_ref") or pack["contract"]).body
    return contract["input_schema_ref"]


def test_a_platform_pack_with_inputs_the_studio_cannot_hold_copies_without_them(ana, db):  # noqa: F811
    def widen(body: dict) -> dict:
        body["properties"] = {
            "orderId": {"title": "Order", "type": "string"},
            **{f"field_{i}": {"title": f"Field {i}", "type": "string"} for i in range(11)},
        }
        body["required"] = []
        return body

    _republish(db, "schema", _schema_key(db, "refund-triage"), widen)
    res = _copy(ana, "refund-triage")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["draft"]["inputFields"]) == 10
    paths = [i["path"] for i in body["issues"]]
    assert paths == ["input_fields[orderId]", "input_fields[field_10]"]
    assert (
        body["issues"][0]["message"] == "The input orderId cannot be edited in the Studio and was left out."
    )
    check = ana.post(f"{_base(ana)}/packs:validate", json=body["draft"]).json()
    assert check == {"ok": True, "issues": []}, check


def test_a_pack_that_cannot_form_a_draft_is_not_editable(ana, db):  # noqa: F811
    def bad_entry(body: dict) -> dict:
        body["entry_node_id"] = "Not A Step"
        return body

    _republish(db, "workflow", registry.latest(db, "pack", "refund-triage").body["workflow"], bad_entry)
    res = _copy(ana, "refund-triage")
    assert res.status_code == 422
    assert res.json()["code"] == "NOT_EDITABLE"
    assert res.json()["detail"] == "This pack cannot be opened in the Studio."
