"""Hosting the runtime in one process: settings, Temporal connect rules, the embedded worker supervisor, the
Cloud SQL URL and the ops runtime-status route. No test connects to Temporal Cloud."""

import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import db as app_db
from app import settings, temporal_client
from app.main import create_app
from app.worker import embedded
from app.worker import runtime as worker_main
from tests.test_ops_auth import CLAIMS, TOKEN, firebase_mode, stub_claims  # noqa: F401

CLOUD_SQL_URL = "postgresql://nm_app:s3cret@/nm?host=/cloudsql/proj:asia-northeast1:nm-db"


# --- settings -------------------------------------------------------------------------------------------


def test_concurrency_and_pool_default_to_8_and_ignore_bad_values(monkeypatch):
    for name in ("NM_WORKER_CONCURRENCY", "NM_DB_POOL_MAX"):
        monkeypatch.delenv(name, raising=False)
    assert (settings.worker_concurrency(), settings.db_pool_max()) == (8, 8)
    monkeypatch.setenv("NM_WORKER_CONCURRENCY", "4")
    monkeypatch.setenv("NM_DB_POOL_MAX", "10")
    assert (settings.worker_concurrency(), settings.db_pool_max()) == (4, 10)
    monkeypatch.setenv("NM_WORKER_CONCURRENCY", "zero")
    monkeypatch.setenv("NM_DB_POOL_MAX", "0")
    assert (settings.worker_concurrency(), settings.db_pool_max()) == (8, 8)


def test_activity_threads_never_exceed_the_pool(monkeypatch):
    monkeypatch.setenv("NM_WORKER_CONCURRENCY", "20")
    monkeypatch.setenv("NM_DB_POOL_MAX", "10")
    assert worker_main.activity_threads() == 10
    monkeypatch.setenv("NM_WORKER_CONCURRENCY", "4")
    assert worker_main.activity_threads() == 4


def test_the_pool_is_sized_from_the_environment_and_the_cloud_sql_url_passes_through(monkeypatch):
    seen = {}

    class FakePool:
        def __init__(self, url, **kwargs):
            seen.update(url=url, **kwargs)

    monkeypatch.setattr(app_db, "ConnectionPool", FakePool)
    monkeypatch.setattr(app_db, "_pool", None)
    monkeypatch.setenv("NM_DB_POOL_MAX", "10")
    monkeypatch.setenv("NM_DATABASE_URL", CLOUD_SQL_URL)
    try:
        app_db.get_pool()
    finally:
        monkeypatch.setattr(app_db, "_pool", None)
    assert seen["max_size"] == 10
    assert seen["url"] == CLOUD_SQL_URL  # the unix-socket URL goes to psycopg untouched


def test_the_database_url_is_returned_untouched(monkeypatch):
    monkeypatch.setenv("NM_DATABASE_URL", CLOUD_SQL_URL)
    assert settings.database_url() == CLOUD_SQL_URL


# --- temporal connect -----------------------------------------------------------------------------------


@pytest.fixture
def connect_calls(monkeypatch):
    calls = []

    async def fake_connect(target, *, plugins, **kwargs):
        assert [type(p).__name__ for p in plugins] == ["GoogleAdkPlugin"]  # every client carries ADK's plugin
        calls.append((target, kwargs))
        return "client"

    monkeypatch.setattr(temporal_client.Client, "connect", fake_connect)
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "nm.abc12")
    return calls


def test_an_api_key_means_tls_for_a_regional_endpoint(connect_calls, monkeypatch):
    monkeypatch.setenv("TEMPORAL_TARGET", "asia-northeast1.gcp.api.temporal.io:7233")
    monkeypatch.setenv("TEMPORAL_API_KEY", "k")
    asyncio.run(temporal_client.connect())
    assert connect_calls == [
        ("asia-northeast1.gcp.api.temporal.io:7233", {"namespace": "nm.abc12", "api_key": "k", "tls": True})
    ]


def test_no_key_stays_plaintext_locally(connect_calls, monkeypatch):
    monkeypatch.setenv("TEMPORAL_TARGET", "127.0.0.1:7243")
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    asyncio.run(temporal_client.connect())
    assert connect_calls == [("127.0.0.1:7243", {"namespace": "nm.abc12"})]


# --- embedded worker ------------------------------------------------------------------------------------


class FakeWorker:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.stopped = asyncio.Event()

    async def run(self):
        if self.fail:
            raise RuntimeError("poll failed")
        await self.stopped.wait()

    async def shutdown(self):
        self.stopped.set()


def _until(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_failing_worker_is_retried_then_runs_and_stops_cleanly(monkeypatch):
    monkeypatch.setattr(embedded, "BACKOFF_START_S", 0.01)
    workers = []

    async def connector():
        return "client"

    def factory(client, pool):
        workers.append(FakeWorker(fail=len(workers) < 2))
        return workers[-1]

    ew = embedded.EmbeddedWorker(connector, factory)
    ew.start()
    assert _until(lambda: ew.running and len(workers) == 3)  # two failures, then one that stays up
    ew.stop()
    assert not ew.running and workers[-1].stopped.is_set()


def test_a_connection_failure_never_raises_and_keeps_retrying(monkeypatch):
    monkeypatch.setattr(embedded, "BACKOFF_START_S", 0.01)
    attempts = []

    async def connector():
        attempts.append(1)
        raise ConnectionError("temporal down")

    ew = embedded.EmbeddedWorker(connector, lambda c, p: FakeWorker())
    ew.start()
    assert _until(lambda: len(attempts) >= 3)
    assert not ew.running
    ew.stop()


def test_the_lifespan_starts_and_stops_the_worker_only_when_asked(monkeypatch):
    events = []
    monkeypatch.setattr(embedded, "start_embedded", lambda: events.append("start"))
    monkeypatch.setattr(embedded, "stop_embedded", lambda: events.append("stop"))

    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.delenv("NM_EMBEDDED_WORKER", raising=False)
    with TestClient(create_app()):
        pass
    assert events == []
    monkeypatch.setenv("NM_EMBEDDED_WORKER", "1")
    with TestClient(create_app()):
        assert events == ["start"]
    assert events == ["start", "stop"]
    monkeypatch.setenv("NM_RUNTIME", "off")
    events.clear()
    with TestClient(create_app()):
        pass
    assert events == []


# --- /v1/ops/runtime/status ----------------------------------------------------------------------------


def test_status_with_the_runtime_off(client, monkeypatch):
    monkeypatch.delenv("NM_RUNTIME", raising=False)
    r = client.get("/v1/ops/runtime/status")
    assert r.status_code == 200
    assert r.json() == {
        "runtime": "off",
        "workspace": "demo",
        "database": "off",
        "temporal": "off",
        "worker": "not_embedded",
        "definitionsApplied": 0,
    }


def test_status_reports_each_part(client, db, monkeypatch):
    from app.routers import ops_runtime_status as route

    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_WORKSPACE", "live")
    monkeypatch.setenv("NM_EMBEDDED_WORKER", "1")
    for kind, key, version in (("pack", "a", 1), ("pack", "a", 2), ("agent", "b", 1)):
        db.execute(
            "INSERT INTO definition_versions (kind, key, version, digest, body, source, published_by, reason)"
            " VALUES (%s, %s, %s, 'd', '{}', 'file', 't', 'r')",
            (kind, key, version),
        )
    db.commit()
    monkeypatch.setattr(route, "_temporal", lambda: None)
    monkeypatch.setattr(embedded, "current", lambda: type("W", (), {"running": True})())
    assert client.get("/v1/ops/runtime/status").json() == {
        "runtime": "on",
        "workspace": "live",
        "database": "ok",
        "temporal": "ok",
        "worker": "running",
        "definitionsApplied": 2,
    }
    monkeypatch.setattr(embedded, "current", lambda: None)
    assert client.get("/v1/ops/runtime/status").json()["worker"] == "stopped"
    monkeypatch.delenv("NM_EMBEDDED_WORKER")
    assert client.get("/v1/ops/runtime/status").json()["worker"] == "not_embedded"


def test_status_errors_do_not_leak_the_connection_string_or_key(client, monkeypatch):
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_DATABASE_URL", "postgresql://u:topsecret@127.0.0.1:1/x")
    monkeypatch.setenv("TEMPORAL_API_KEY", "topsecret-key")

    def boom(*args, **kwargs):
        raise OSError("topsecret topsecret-key")

    monkeypatch.setattr(temporal_client, "get_client", boom)
    monkeypatch.setattr(app_db, "get_pool", boom)
    r = client.get("/v1/ops/runtime/status")
    assert r.status_code == 200
    assert r.json()["database"] == "error" and r.json()["temporal"] == "error"
    assert "topsecret" not in r.text


@pytest.mark.usefixtures("firebase_mode")
def test_status_needs_an_ops_role_and_support_may_read(client, monkeypatch):
    monkeypatch.delenv("NM_RUNTIME", raising=False)
    assert client.get("/v1/ops/runtime/status").status_code == 401
    stub_claims(monkeypatch, {**CLAIMS, "email": "someone@customer.example"})
    assert client.get("/v1/ops/runtime/status", headers=TOKEN).status_code == 403
    stub_claims(monkeypatch, {**CLAIMS, "email": "sam.support@newmachin.es"})
    assert client.get("/v1/ops/runtime/status", headers=TOKEN).status_code == 200


def test_a_hung_probe_reports_error_within_a_few_seconds(client, monkeypatch):
    from app.routers import ops_runtime_status as route

    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setattr(route, "PROBE_TIMEOUT_S", 1.5)
    release = threading.Event()
    monkeypatch.setattr(route, "_database", lambda: release.wait(30) or 1)
    monkeypatch.setattr(route, "_temporal", lambda: release.wait(30))
    started = time.monotonic()
    r = client.get("/v1/ops/runtime/status")
    release.set()
    # Both probes share one deadline (1.5 + 1 s); waiting on them one after the other would take about 5 s.
    # The bound sits halfway, so a loaded machine's request overhead cannot fail it.
    assert time.monotonic() - started < 3.75
    assert r.json()["database"] == "error" and r.json()["temporal"] == "error"


def test_system_info_bounds_the_connect_and_the_call(monkeypatch):
    monkeypatch.setattr(temporal_client, "_client", None)
    monkeypatch.setattr(temporal_client, "_connecting", None)

    async def hang():
        await asyncio.sleep(30)

    monkeypatch.setattr(temporal_client, "connect", hang)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        temporal_client.system_info(timeout=0.3)
    assert time.monotonic() - started < 3


def test_the_db_probe_gives_up_after_its_timeout(monkeypatch):
    import psycopg_pool

    class StuckPool:
        def connection(self, timeout=None):
            raise psycopg_pool.PoolTimeout(f"timeout {timeout}")

    monkeypatch.setattr(app_db, "get_pool", StuckPool)
    with pytest.raises(psycopg_pool.PoolTimeout, match="0.5"):
        app_db.probe(0.5)


# --- supervisor edges and shutdown ---------------------------------------------------------------------


def test_backoff_doubles_up_to_the_cap(monkeypatch):
    monkeypatch.setattr(embedded, "BACKOFF_START_S", 0.01)
    monkeypatch.setattr(embedded, "BACKOFF_MAX_S", 0.04)
    delays = []

    async def connector():
        raise ConnectionError("down")

    ew = embedded.EmbeddedWorker(connector, lambda c, p: FakeWorker())

    async def record(seconds):
        delays.append(seconds)
        await asyncio.sleep(0)

    monkeypatch.setattr(ew, "_sleep_or_stop", record)
    ew.start()
    assert _until(lambda: len(delays) >= 6)
    ew.stop()
    assert delays[:5] == [0.01, 0.02, 0.04, 0.04, 0.04]


def test_stop_does_not_wait_for_a_hanging_connect():
    cancelled = threading.Event()

    async def connector():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    ew = embedded.EmbeddedWorker(connector, lambda c, p: FakeWorker())
    ew.start()
    assert _until(lambda: ew.alive)
    time.sleep(0.1)
    started = time.monotonic()
    assert ew.stop() is True
    assert time.monotonic() - started < 3 and cancelled.is_set()


def test_the_pool_stays_open_while_the_worker_thread_is_alive(monkeypatch, caplog):
    resets = []
    monkeypatch.setattr(app_db, "reset_pool", lambda: resets.append(1))
    monkeypatch.setattr(embedded, "start_embedded", lambda: None)
    monkeypatch.setattr(embedded, "stop_embedded", lambda: False)
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setenv("NM_EMBEDDED_WORKER", "1")
    with TestClient(create_app()):
        pass
    assert resets == []
    assert "database pool stays open" in caplog.text


def test_embedded_start_warns_when_concurrency_reaches_the_pool(monkeypatch, caplog):
    monkeypatch.setattr(embedded.EmbeddedWorker, "start", lambda self: None)
    monkeypatch.setenv("NM_WORKER_CONCURRENCY", "8")
    monkeypatch.setenv("NM_DB_POOL_MAX", "8")
    embedded.start_embedded()
    assert "NM_WORKER_CONCURRENCY" in caplog.text
    caplog.clear()
    monkeypatch.setenv("NM_DB_POOL_MAX", "10")
    embedded.start_embedded()
    embedded.stop_embedded()
    assert "NM_WORKER_CONCURRENCY" not in caplog.text


def test_the_worker_gets_a_graceful_shutdown_inside_the_cloud_run_window():
    assert worker_main.GRACEFUL_SHUTDOWN.total_seconds() <= 5
    assert embedded.STOP_TIMEOUT_S <= 8


def test_a_short_waiter_timing_out_does_not_cancel_a_connect_another_caller_awaits(monkeypatch):
    monkeypatch.setattr(temporal_client, "_client", None)
    monkeypatch.setattr(temporal_client, "_connecting", None)
    connects = []

    async def slow_connect():
        connects.append(1)
        await asyncio.sleep(1.0)
        return "the-client"

    monkeypatch.setattr(temporal_client, "connect", slow_connect)
    got = {}
    waiter = threading.Thread(target=lambda: got.update(client=temporal_client.get_client()))
    waiter.start()
    time.sleep(0.1)
    with pytest.raises(TimeoutError):
        temporal_client.get_client(timeout=0.2)  # the status probe gives up; the connect goes on
    waiter.join(timeout=5)
    assert got == {"client": "the-client"} and connects == [1]
    assert temporal_client.get_client(timeout=0.2) == "the-client"  # cached for the next probe


def test_closing_the_pool_is_bounded(monkeypatch):
    seen = {}

    class FakePool:
        def close(self, timeout=None):
            seen["timeout"] = timeout

    monkeypatch.setattr(app_db, "_pool", FakePool())
    app_db.reset_pool()
    assert seen["timeout"] <= 1.0
