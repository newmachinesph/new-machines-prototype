"""Postgres access: a lazy connection pool and a minimal SQL-file migrator."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

POOL_CLOSE_TIMEOUT_S = 1.0  # shutdown must fit Cloud Run's 10 s with the worker stop
MIGRATE_LOCK = 7_204_100_002  # pg advisory lock key; app.defs.registry uses ...001

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings.database_url(),
                min_size=1,
                max_size=settings.db_pool_max(),
                open=True,
                kwargs={"row_factory": dict_row, "autocommit": False},
            )
        return _pool


def reset_pool() -> None:
    """Close and drop the singleton pool (tests switch databases between runs)."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close(timeout=POOL_CLOSE_TIMEOUT_S)


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection]:
    """Yield a pooled connection, or a direct one when `url` is given. Commits on success."""
    if url is not None:
        with psycopg.connect(url, row_factory=dict_row) as conn:
            yield conn
        return
    with get_pool().connection() as conn:
        yield conn


def probe(timeout: float) -> int:
    """Count the applied definitions (distinct kind and key), waiting at most `timeout` seconds for a pooled
    connection. Raises when the database cannot be reached; for the ops status route."""
    with get_pool().connection(timeout=timeout) as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM (SELECT DISTINCT kind, key FROM definition_versions) d"
        ).fetchone()
    return int(row["n"])


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations/*.sql in name order, one transaction each. Returns applied names.

    Holds a session advisory lock throughout, so processes starting together (API and worker) apply each
    file once: the later one waits, then reads the applied names again and finds nothing left."""
    conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATE_LOCK,))
    conn.commit()
    try:
        return _apply_pending(conn)
    finally:
        if conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
            conn.rollback()
        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATE_LOCK,))
        conn.commit()


def _apply_pending(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
    )
    conn.commit()
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        try:
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(path.name)
    return applied
