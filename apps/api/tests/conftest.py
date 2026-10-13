import os

# The API verifies sign-in unless AUTH_MODE=dev is set explicitly; the suite runs in dev mode by default
# (set before app.main is imported, since importing it builds the app).
os.environ.setdefault("AUTH_MODE", "dev")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg import sql  # noqa: E402

from app import db as app_db  # noqa: E402
from app import settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import reset_store  # noqa: E402

TEST_DB_NAME = "nm_test"


@pytest.fixture
def client() -> TestClient:
    reset_store()
    return TestClient(create_app())


def _ensure_test_database() -> None:
    with psycopg.connect(settings.database_url(), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME)))


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch):
    """Opt-in Postgres fixture: migrated, empty `nm_test` database. Yields a dict_row connection."""
    _ensure_test_database()
    monkeypatch.setenv("NM_DATABASE_URL", settings.test_database_url())
    app_db.reset_pool()
    with app_db.connect(settings.test_database_url()) as conn:
        app_db.migrate(conn)
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
        ).fetchall()
        if tables:
            names = sql.SQL(", ").join(sql.Identifier(t["tablename"]) for t in tables)
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(names))
        conn.execute("ALTER SEQUENCE run_number RESTART")  # run ids are run_2001, run_2002, ... per test
        conn.commit()
        yield conn
    app_db.reset_pool()
