import os
from urllib.parse import urlparse

# The API verifies sign-in unless AUTH_MODE=dev is set explicitly; the suite runs in dev mode by default
# (set before app.main is imported, since importing it builds the app).
os.environ.setdefault("AUTH_MODE", "dev")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from psycopg import sql  # noqa: E402

from app import auth, settings  # noqa: E402
from app import db as app_db  # noqa: E402
from app.defs import registry  # noqa: E402
from app.defs.loader import load_bundle  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import reset_store  # noqa: E402

# The database named by NM_TEST_DATABASE_URL (`nm_test` by default), so parallel runs can each use their own.
TEST_DB_NAME = urlparse(settings.test_database_url()).path.lstrip("/") or "nm_test"


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


@pytest.fixture
def defs(db):
    """`db` with every definition file published, as the live workspace has them."""
    registry.apply_bundle(db, load_bundle(settings.defs_dir()))
    db.commit()
    return db


@pytest.fixture
def live_ops(defs, monkeypatch) -> TestClient:
    """The API in the live workspace, signed in as an ops admin with `tests.test_ops_state.OPS`."""
    from tests.test_live_catalog import PROJECT
    from tests.test_ops_state import OPS_EMAIL, _verify

    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_CONNECTOR_MODE", "sandbox")
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setenv("OPS_ADMIN_EMAILS", OPS_EMAIL)
    monkeypatch.setattr(auth.id_token, "verify_firebase_token", _verify)
    reset_store()
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _fresh_platform_mcp_probe():
    """`auto` mode caches the platform MCP server check for a minute per process; no test inherits one."""
    from app.runtime import drivers

    drivers.reset_probe_cache()
    yield
    drivers.reset_probe_cache()
