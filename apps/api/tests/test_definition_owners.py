"""Sub-project C, part 1: definition owners, owner-namespaced keys and what each org may see."""

import psycopg
import pytest

from app import real_runs
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.defs.snapshot import build_snapshot
from tests.team_seed import clone_agent, clone_pack

PACK = "order-payment-reconciliation"
ORG_A, ORG_B = "org_aaaa000000000001", "org_bbbb000000000002"


def _schema(key: str, body: dict) -> Definition:
    return Definition(kind="schema", key=key, body=body, path=path_for("schema", key))


def test_org_keys_are_namespaced_by_the_org():
    org = "org_3f2a9c1b7d4e5f60"
    assert owners.org_namespace(org) == "org-3f2a9c1b7d4e5f60"
    assert owners.org_key(org, "invoice-nudges") == "org-3f2a9c1b7d4e5f60--invoice-nudges"
    assert owners.in_org("org-3f2a9c1b7d4e5f60--x", org)
    assert not owners.in_org("org-3f2a9c1b7d4e5f60--x", "org_0000000000000000")
    assert owners.name_of("org-3f2a9c1b7d4e5f60--invoice-nudges") == "invoice-nudges"
    assert owners.is_reserved("a--b") and not owners.is_reserved("refund-triage")


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Invoice nudges!", "invoice-nudges"),
        ("  Weekly   Stock  ", "weekly-stock"),
        ("2026 plan", "x-2026-plan"),
        ("請求書", "untitled"),
        ("a" * 60, "a" * 40),
    ],
)
def test_slugify_makes_a_valid_name(text, name):
    assert owners.slugify(text) == name
    assert owners.is_name(name)


def test_a_builder_version_is_stored_and_an_unknown_source_is_refused(defs):
    v = registry.publish(
        defs, _schema("shared/test-only", {"type": "object"}), "ana", "test", source=registry.BUILDER
    )
    assert v.source == "builder"
    with pytest.raises(psycopg.errors.CheckViolation):
        registry.publish(defs, _schema("shared/test-two", {"type": "array"}), "ana", "test", source="other")
    defs.rollback()


def test_a_definition_without_an_owner_row_is_the_platforms(defs):
    assert registry.owner_of(defs, "pack", PACK) == owners.PLATFORM


def test_claim_is_idempotent_for_its_owner_and_refused_for_anyone_else(defs):
    key = owners.org_key(ORG_A, "mine")
    registry.claim(defs, "agent", key, owners.org_owner(ORG_A), "test")
    registry.claim(defs, "agent", key, owners.org_owner(ORG_A), "test")
    with pytest.raises(registry.KeyTaken):
        registry.claim(defs, "agent", key, owners.org_owner(ORG_B), "test")
    with pytest.raises(registry.KeyTaken):
        registry.claim(defs, "pack", PACK, owners.org_owner(ORG_A), "test")
    assert registry.owner_of(defs, "agent", key) == owners.org_owner(ORG_A)


def test_each_org_sees_its_own_definitions_and_the_platforms(defs):
    mine = clone_pack(defs, PACK, ORG_A, "recon")
    agent = clone_agent(defs, "finance-agent", ORG_A, "matcher")
    ours = {("pack", mine), ("workflow", mine), ("contract", mine), ("agent", agent)}
    seen_a = {(v.kind, v.key) for v in registry.latest_visible(defs, ORG_A)}
    seen_b = {(v.kind, v.key) for v in registry.latest_visible(defs, ORG_B)}
    seen_platform = {(v.kind, v.key) for v in registry.latest_visible(defs, None)}
    assert ours <= seen_a
    assert not ours & seen_b and not ours & seen_platform
    assert ("pack", PACK) in seen_a & seen_b & seen_platform
    assert [v.key for v in registry.owned(defs, ORG_A, "pack")] == [mine]
    assert registry.owned(defs, ORG_B, "pack") == []
    assert registry.team_keys(defs, ORG_A) == ours
    assert registry.team_keys(defs, ORG_B) == set()
    assert registry.visible_bundle(defs, ORG_A).get("pack", mine) is not None
    assert registry.visible_bundle(defs, ORG_B).get("pack", mine) is None


def test_a_snapshot_pins_an_org_pack_only_for_its_org(defs):
    mine = clone_pack(defs, PACK, ORG_A, "recon")
    snapshot = build_snapshot(defs, mine, ORG_A, {}, set())
    assert snapshot["defs"]["contract"][mine]["body"]["org_id"] == ORG_A
    with pytest.raises(LookupError, match="not available"):
        build_snapshot(defs, mine, ORG_B, {}, set())
    assert registry.hidden_from(defs, [("pack", mine), ("pack", PACK)], ORG_B) == [("pack", mine)]
    assert registry.hidden_from(defs, [("pack", mine)], ORG_A) == []


def test_publish_if_changed_skips_an_identical_version(defs):
    d = _schema("shared/same", {"type": "object"})
    assert registry.publish_if_changed(defs, d, "ana", "first", source=registry.BUILDER).version == 1
    assert registry.publish_if_changed(defs, d, "ana", "again", source=registry.BUILDER) is None


def test_the_demo_start_path_only_knows_platform_packs(defs, monkeypatch):
    """`has_pack` guards the demo run start: an org's private pack is not a pack the demo can start, so a
    team key never reaches the input check (and its private schema never shows in a 422)."""
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    mine = clone_pack(defs, PACK, ORG_A, "recon")
    assert real_runs.has_pack(PACK)
    assert not real_runs.has_pack(mine)
    assert not real_runs.has_pack("no-such-pack")


def test_a_private_platform_pack_is_still_a_platform_pack(defs, monkeypatch):
    """`has_pack` asks who owns the pack, not how visible it is: a platform row marked private still
    counts."""
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    defs.execute(
        "INSERT INTO definition_owners (kind, key, owner_kind, owner_id, visibility, created_by) "
        "VALUES ('pack', %s, 'platform', NULL, 'private', 'test')",
        (PACK,),
    )
    defs.commit()
    assert registry.owner_of(defs, "pack", PACK) == owners.Owner("platform", None, "private")
    assert real_runs.has_pack(PACK)


def test_claim_holds_the_registry_lock(defs):
    """A claim serialises with every version insert: it takes the registry's transaction-scoped advisory
    lock itself, so a caller need not take it first."""
    registry.claim(defs, "agent", owners.org_key(ORG_A, "locked"), owners.org_owner(ORG_A), "test")
    held = defs.execute(
        "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
        "AND (classid::bigint << 32) + objid::bigint = %s",
        (registry._ADVISORY_LOCK,),
    ).fetchone()
    assert held is not None
    defs.commit()
    released = defs.execute(
        "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
    ).fetchone()
    assert released is None
