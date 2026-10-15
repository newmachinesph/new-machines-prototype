import threading
from pathlib import Path

from app import db as app_db
from app import settings

EXPECTED_TABLES = {
    "definition_versions",
    "definition_owners",
    "runs",
    "receipt_entries",
    "run_tasks",
    "memory_items",
    "orgs",
    "org_members",
    "installations",
    "connections",
    "api_tokens",
    "connector_settings",
    "platform_settings",
    "ops_audit",
    "tool_results",
    "network_reviewers",
    "schema_migrations",
}
APP_TABLES = sorted(EXPECTED_TABLES - {"schema_migrations"})


def test_migrate_applies_init_once(db):
    # The fixture already migrated; a fresh database would have applied 001_init.sql.
    applied = db.execute("SELECT name FROM schema_migrations ORDER BY name").fetchall()
    assert "001_init.sql" in [row["name"] for row in applied]
    assert app_db.migrate(db) == []


def test_migrate_reports_applied_names_on_fresh_schema(db):
    db.execute("DELETE FROM schema_migrations")
    for table in APP_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    db.execute("DROP SEQUENCE run_number")
    db.commit()
    assert app_db.migrate(db) == [p.name for p in sorted(Path(app_db.MIGRATIONS_DIR).glob("*.sql"))]
    assert app_db.migrate(db) == []


def _drop_schema(db) -> None:
    db.execute("DROP TABLE IF EXISTS schema_migrations")
    for table in APP_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    db.execute("DROP SEQUENCE run_number")
    db.commit()


def test_concurrent_migrations_apply_each_file_once(db):
    """The API and the worker may start together: migrate holds an advisory lock, so the second one waits
    and then finds nothing left to apply."""
    _drop_schema(db)
    start, results, errors = threading.Barrier(3), [], []

    def run() -> None:
        with app_db.connect(settings.test_database_url()) as conn:
            start.wait()
            try:
                results.append(app_db.migrate(conn))
            except Exception as exc:  # collected and asserted below
                errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert errors == []
    names = [p.name for p in sorted(Path(app_db.MIGRATIONS_DIR).glob("*.sql"))]
    assert sorted(results, key=len) == [[], [], names]


def test_all_tables_exist(db):
    rows = db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    assert {row["table_name"] for row in rows} >= EXPECTED_TABLES


def test_vector_extension_installed(db):
    row = db.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()
    assert row is not None
