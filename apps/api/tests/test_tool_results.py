"""`tool_results` keeps a permitted side-effecting call's result only while its run can still retry the
call: sealing the run's receipt deletes them, and migration 010 removed those of runs sealed before (and
the read payloads stored before reads stopped being kept)."""

import pytest
from temporalio.exceptions import ApplicationError

from app import db as app_db
from app.worker import activities
from app.worker.activities import NodeCall
from tests.test_workflow import _new_run, runtime_env  # noqa: F401  (runtime_env is a fixture)

KEY = "send:1:tool.call:4"
READ_KEY = "read:1:tool.call:2"
UNKNOWN_KEY = "odd:1:tool.call:3"


def _keep(conn, run_id: str, key: str = KEY) -> None:
    conn.execute(
        'INSERT INTO tool_results (run_id, event_key, result) VALUES (%s, %s, \'{"id": "r-1"}\')',
        (run_id, key),
    )
    conn.commit()


def _kept(conn) -> set[str]:
    conn.commit()
    return {r["run_id"] for r in conn.execute("SELECT run_id FROM tool_results").fetchall()}


def _seal(run_id: str) -> None:
    failed = (activities.event_key(None, 0, "run.failed", 0), "run.failed", None, {"reason": "stopped"})
    with app_db.connect() as conn:
        activities.record_events(conn, run_id, [failed])
        conn.commit()


def test_sealing_a_run_deletes_the_results_kept_for_its_retries(runtime_env):  # noqa: F811
    sealed, _ = _new_run(runtime_env)
    running, _ = _new_run(runtime_env)
    _keep(runtime_env, sealed)
    _keep(runtime_env, running)
    _seal(sealed)
    assert _kept(runtime_env) == {running}


def test_migration_010_prunes_sealed_runs_and_requires_created_at(runtime_env):  # noqa: F811
    db = runtime_env
    try:
        sealed, _ = _new_run(db)
        running, _ = _new_run(db)
        _seal(sealed)
        # Rows of a run sealed before 010 (the seal did not prune then), one without created_at.
        db.execute("DELETE FROM schema_migrations WHERE name = '010_tool_results_prune.sql'")
        db.execute("ALTER TABLE tool_results ALTER COLUMN created_at DROP NOT NULL")
        db.commit()
        _keep(db, sealed)
        _keep(db, running)
        db.execute("UPDATE tool_results SET created_at = NULL WHERE run_id = %s", (running,))
        db.commit()
        assert app_db.migrate(db) == ["010_tool_results_prune.sql"]
        assert _kept(db) == {running}
        nullable = db.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'tool_results' AND column_name = 'created_at'"
        ).fetchone()["is_nullable"]
        assert nullable == "NO"
    finally:  # whatever failed above, `nm_test` keeps 010 for the tests after this one
        db.rollback()
        app_db.migrate(db)


def test_migration_010_drops_read_payloads_stored_before_reads_stopped_being_kept(runtime_env):  # noqa: F811
    db = runtime_env
    try:
        run, _ = _new_run(db)
        db.execute("DELETE FROM schema_migrations WHERE name = '010_tool_results_prune.sql'")
        db.commit()
        for key, action_class in ((READ_KEY, "read"), (KEY, "write"), (UNKNOWN_KEY, "")):
            activities.record_events(
                db, run, [(key, "tool.call", None, {"id": "c", "action_class": action_class})]
            )
            _keep(db, run, key)
        assert app_db.migrate(db) == ["010_tool_results_prune.sql"]
        db.commit()
        left = {r["event_key"] for r in db.execute("SELECT event_key FROM tool_results").fetchall()}
        assert left == {KEY, UNKNOWN_KEY}
    finally:
        db.rollback()
        app_db.migrate(db)


def test_a_late_commit_cannot_write_a_result_back_after_the_seal(runtime_env):  # noqa: F811
    run, _ = _new_run(runtime_env)
    _seal(run)
    call = NodeCall(run_id=run, node_id="n1", attempt=1, step=0, snapshot={}, state={})
    activities._commit(call, [], activities._keep_result(run, KEY, {"id": "r-1"}))
    assert _kept(runtime_env) == set()


def test_a_retried_call_whose_result_went_with_the_seal_is_refused(runtime_env):  # noqa: F811
    run, _ = _new_run(runtime_env)
    call = NodeCall(run_id=run, node_id="n1", attempt=1, step=0, snapshot={}, state={})
    key = activities.event_key("n1", 1, "tool.call", 0)
    entry = {"id": "c", "ok": True, "action_class": "write", "policy": {"verdict": "PERMIT"}}
    with app_db.connect() as conn:
        activities.record_events(conn, run, [(key, "tool.call", "n1", entry)])
        conn.commit()
    _seal(run)
    with pytest.raises(ApplicationError) as err:
        activities._tool_call(call, "x.y", {}, "c", False)
    assert err.value.type == activities.RUN_SEALED and err.value.non_retryable
