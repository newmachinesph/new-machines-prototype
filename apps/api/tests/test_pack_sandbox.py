"""Sandbox responses per pack: a pack's own file wins over the shared one for that pack's runs only."""

import json

from app.runtime import drivers, gateway


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(data).encode("utf-8"))


def _roots(tmp_path):
    shared, packs = tmp_path / "shared", tmp_path / "packs"
    _write(shared / "gmail" / "list_threads.json", {"from": "shared"})
    _write(shared / "gmail" / "create_draft.json", {"id": "shared-draft"})
    _write(packs / "lead-pack" / "sandbox" / "gmail" / "list_threads.json", {"from": "pack"})
    return shared, packs


def test_a_pack_s_own_response_wins(tmp_path):
    shared, packs = _roots(tmp_path)
    driver = drivers.SandboxDriver(root=shared, pack="lead-pack", packs_root=packs)
    result = driver.execute("gmail", {"id": "list_threads"}, {})
    assert result.ok and result.mocked and result.data == {"from": "pack"}


def test_a_tool_the_pack_has_no_file_for_falls_back_to_the_shared_one(tmp_path):
    shared, packs = _roots(tmp_path)
    driver = drivers.SandboxDriver(root=shared, pack="lead-pack", packs_root=packs)
    assert driver.execute("gmail", {"id": "create_draft"}, {}).data == {"id": "shared-draft"}


def test_another_pack_and_no_pack_use_the_shared_response(tmp_path):
    shared, packs = _roots(tmp_path)
    for pack in ("other-pack", None):
        driver = drivers.SandboxDriver(root=shared, pack=pack, packs_root=packs)
        assert driver.execute("gmail", {"id": "list_threads"}, {}).data == {"from": "shared"}


def test_an_unsafe_pack_name_is_ignored(tmp_path):
    shared, packs = _roots(tmp_path)
    _write(tmp_path / "evil" / "gmail" / "list_threads.json", {"from": "outside"})
    for pack in ("../evil", "lead-pack/../../evil", "a b"):
        driver = drivers.SandboxDriver(root=shared, pack=pack, packs_root=packs)
        assert driver.pack is None
        assert driver.execute("gmail", {"id": "list_threads"}, {}).data == {"from": "shared"}


def test_driver_for_passes_the_pack_to_sandbox_drivers():
    driver = drivers.driver_for({"toolkit": "gmail"}, "sandbox", pack="lead-pack")
    assert isinstance(driver, drivers.SandboxDriver) and driver.pack == "lead-pack"
    assert drivers.driver_for({"toolkit": "gmail"}, "sandbox").pack is None


def test_the_run_s_pack_is_the_one_its_snapshot_pins():
    assert gateway._pack_key({"defs": {"pack": {"refund-triage": {"body": {}}}}}) == "refund-triage"
    assert gateway._pack_key({"defs": {}}) is None
    assert gateway._pack_key({"defs": {"pack": {"a": {}, "b": {}}}}) is None


def test_an_unrouted_sandbox_run_reads_its_pack_s_data():
    snapshot = {"defs": {"pack": {"lead-pack": {"body": {}}}}, "connector_mode": "sandbox"}
    driver = gateway.driver_of(snapshot, "gmail", {"toolkit": "gmail"}, "live")
    assert isinstance(driver, drivers.SandboxDriver) and driver.pack == "lead-pack"
