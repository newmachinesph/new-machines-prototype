"""Sub-project D, part 3: another workspace sees a listed definition only at its approved version, the ops
view and the file export never see it, and a run pins only what its org may see."""

import pytest

from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.defs.snapshot import build_snapshot
from tests.live_seed import add_org
from tests.publishing_seed import add_listing, add_version, approve_and_list, defs_of
from tests.team_seed import clone_agent, clone_pack

PACK = "order-payment-reconciliation"
ACME, BUYER = "org_acme000000000001", "org_buyer00000000002"
THIRD = "org_third00000000003"


def _republish(db, kind: str, key: str, **changes) -> int:
    """A later builder version of kind/key (a draft nobody has approved); returns its version."""
    v = registry.latest(db, kind, key)
    d = Definition(
        kind=kind, key=key, body={**v.body, **changes}, files=dict(v.files), path=path_for(kind, key)
    )
    return registry.publish(db, d, "test", "a later draft", source=registry.BUILDER).version


@pytest.fixture
def listed_agent(defs):
    add_org(defs, ACME, "Acme")
    add_org(defs, BUYER, "Buyer Co")
    defs.commit()
    agent = clone_agent(defs, "finance-agent", ACME, "matcher", title="Matcher")
    listing = add_listing(defs, "agent", agent, ACME, name="Matcher")
    version = add_version(defs, listing, 1, defs_of(defs, [("agent", agent)]))
    approve_and_list(defs, listing, version)
    draft = _republish(defs, "agent", agent, name="Matcher draft")
    defs.commit()
    return agent, listing, draft


def _seen(db, org: str | None) -> dict[tuple[str, str], int]:
    return {(v.kind, v.key): v.version for v in registry.latest_visible(db, org)}


def test_a_buyer_sees_the_approved_version_and_the_publisher_its_latest(defs, listed_agent):
    agent, _, draft = listed_agent
    assert _seen(defs, BUYER)[("agent", agent)] == 1
    assert _seen(defs, ACME)[("agent", agent)] == draft == 2
    assert registry.visible_version(defs, "agent", agent, BUYER).body["name"] == "Matcher"
    assert registry.visible_version(defs, "agent", agent, ACME).version == 2


def test_the_ops_view_and_the_export_never_see_listed_definitions(defs, listed_agent):
    agent, _, _ = listed_agent
    assert ("agent", agent) not in _seen(defs, None)
    assert registry.visible_version(defs, "agent", agent, None) is None


def test_unlisted_and_private_definitions_are_seen_by_their_owner_only(defs, listed_agent):
    agent, listing, _ = listed_agent
    private = clone_agent(defs, "finance-agent", ACME, "secret")
    defs.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    defs.commit()
    for key in (agent, private):
        assert ("agent", key) not in _seen(defs, BUYER)
        assert registry.visible_version(defs, "agent", key, BUYER) is None
        assert ("agent", key) in _seen(defs, ACME)


def test_platform_definitions_are_unchanged_for_everyone(defs, listed_agent):
    latest = registry.latest(defs, "pack", PACK).version
    for org in (ACME, BUYER, None):
        assert registry.visible_version(defs, "pack", PACK, org).version == latest


def test_each_definition_is_listed_once_in_key_order(defs, listed_agent):
    keys = [(v.kind, v.key) for v in registry.latest_visible(defs, BUYER)]
    assert len(keys) == len(set(keys)) and keys == sorted(keys)


def _listed_pack(db) -> tuple[str, str]:
    """ACME's copy of the seed pack, listed at its first release: (pack key, listing id)."""
    key = clone_pack(db, PACK, ACME, "recon", title="Acme recon")
    listing = add_listing(db, "pack", key, ACME, name="Acme recon")
    version = add_version(db, listing, 1, defs_of(db, [("pack", key), ("workflow", key), ("contract", key)]))
    approve_and_list(db, listing, version)
    db.commit()
    return key, listing


def _name(snapshot: dict, key: str) -> str:
    return snapshot["defs"]["pack"][key]["body"]["name"]


def test_a_buyers_snapshot_pins_the_approved_versions(defs, listed_agent):
    key, _ = _listed_pack(defs)
    _republish(defs, "pack", key, name="Acme recon draft")
    defs.commit()
    snap = build_snapshot(defs, key, BUYER, {}, set())
    assert {(v["kind"], v["key"]): v["version"] for v in snap["versions"]}[("pack", key)] == 1
    assert _name(snap, key) == "Acme recon"
    assert _name(build_snapshot(defs, key, ACME, {}, set()), key) == "Acme recon draft"


def test_another_org_cannot_pin_an_unlisted_pack(defs, listed_agent):
    key, listing = _listed_pack(defs)
    defs.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing,))
    defs.commit()
    with pytest.raises(LookupError, match="is not available to"):
        build_snapshot(defs, key, BUYER, {}, set())


def test_pins_hold_an_installation_to_an_older_approved_version(defs, listed_agent):
    key, _ = _listed_pack(defs)
    v2 = _republish(defs, "pack", key, name="Acme recon two")
    defs.execute("UPDATE listed_definitions SET version = %s WHERE kind = 'pack' AND key = %s", (v2, key))
    defs.commit()
    assert _name(build_snapshot(defs, key, BUYER, {}, set()), key) == "Acme recon two"
    assert _name(build_snapshot(defs, key, BUYER, {}, set(), pins={("pack", key): 1}), key) == "Acme recon"


def test_pins_never_reach_a_definition_the_org_may_not_see(defs, listed_agent):
    hidden = clone_pack(defs, PACK, ACME, "hidden")
    with pytest.raises(LookupError, match="is not available to"):
        build_snapshot(defs, hidden, BUYER, {}, set(), pins={("pack", hidden): 1})


def test_unsaved_definitions_are_pinned_at_version_zero_and_never_published(defs, listed_agent):
    seed = registry.latest(defs, "pack", PACK).body
    workflow = registry.latest(defs, "workflow", seed["workflow"]).body
    contract = registry.latest(defs, "contract", seed["contract"]).body
    key = owners.org_key(BUYER, "listing-check")
    unsaved = {
        ("pack", key): Definition("pack", key, {**seed, "slug": key, "workflow": key, "contract": key}),
        ("workflow", key): Definition(
            "workflow", key, {**workflow, "workflow_id": key, "work_contract_ref": key}
        ),
        ("contract", key): Definition("contract", key, {**contract, "contract_id": key}),
    }
    snap = build_snapshot(defs, key, BUYER, {}, set(), unsaved=unsaved)
    pinned = {(v["kind"], v["key"]): v["version"] for v in snap["versions"]}
    assert pinned[("pack", key)] == pinned[("workflow", key)] == pinned[("contract", key)] == 0
    assert registry.latest(defs, "pack", key) is None


def _list_row(db, kind: str, key: str, listing: str, publisher: str = ACME) -> None:
    """A listed_definitions row written straight in, as a faulty writer might."""
    version = registry.latest(db, kind, key).version
    db.execute(
        "INSERT INTO listed_definitions (kind, key, version, listing_id, publisher_org_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (kind, key, version, listing, publisher),
    )


def test_listed_rows_are_trusted_only_for_the_publishers_own_listed_keys(defs, listed_agent):
    _, listing, _ = listed_agent
    add_org(defs, THIRD, "Third Co")
    defs.commit()
    third = clone_agent(defs, "finance-agent", THIRD, "own")
    gone = clone_agent(defs, "finance-agent", ACME, "gone")
    gone_listing = add_listing(defs, "agent", gone, ACME, name="Gone")
    approve_and_list(defs, gone_listing, add_version(defs, gone_listing, 1, defs_of(defs, [("agent", gone)])))
    defs.execute("UPDATE listings SET status = 'unlisted' WHERE id = %s", (gone_listing,))
    _list_row(defs, "pack", PACK, listing)
    _list_row(defs, "agent", third, listing)
    defs.commit()
    seen = _seen(defs, BUYER)
    assert seen[("pack", PACK)] == registry.latest(defs, "pack", PACK).version
    for key in (third, gone):
        assert ("agent", key) not in seen
        assert registry.visible_version(defs, "agent", key, BUYER) is None
    keys = [(v.kind, v.key) for v in registry.latest_visible(defs, BUYER)]
    assert len(keys) == len(set(keys)) and keys == sorted(keys)


def test_a_pin_never_reaches_a_draft_of_a_listed_definition(defs, listed_agent):
    key, _ = _listed_pack(defs)
    draft = _republish(defs, "pack", key, name="Acme recon draft")
    defs.commit()
    with pytest.raises(LookupError, match="is not available to"):
        build_snapshot(defs, key, BUYER, {}, set(), pins={("pack", key): draft})


def test_unsaved_definitions_stay_in_the_orgs_namespace(defs, listed_agent):
    seed = registry.latest(defs, "pack", PACK).body
    with pytest.raises(ValueError, match="outside"):
        build_snapshot(defs, PACK, BUYER, {}, set(), unsaved={("pack", PACK): Definition("pack", PACK, seed)})
