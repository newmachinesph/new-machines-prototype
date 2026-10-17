"""The definition files behind the demo catalog (runtime off) are read once per process, at startup on a
background thread, and a request that arrives during that read waits for it instead of reading again."""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.defs import current
from app.defs.loader import LoadError
from app.defs.model import Bundle, Definition
from app.main import create_app


def _bundle() -> Bundle:
    pack = Definition("pack", "p1", {"slug": "p1", "name": "Pack one"})
    return Bundle({("pack", "p1"): pack})


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Each test reads its own files: the runtime off, nothing read yet, before and after."""
    monkeypatch.delenv("NM_RUNTIME", raising=False)
    current.forget_files()
    yield
    current.forget_files()


def test_warm_reads_the_files_once_and_the_requests_after_it_read_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(current, "load_bundle", lambda root: calls.append(root) or _bundle())
    current.warm()
    assert calls == [current.settings.defs_dir()]
    assert current.latest_bodies("pack") == {"p1": {"slug": "p1", "name": "Pack one"}}
    assert current.latest_bodies("contract") == {}
    assert len(calls) == 1


def test_requests_during_the_warm_up_wait_for_its_read_instead_of_reading_again(monkeypatch):
    calls = []
    started = threading.Event()

    def slow_load(root: Path) -> Bundle:
        calls.append(root)
        started.set()
        time.sleep(0.3)
        return _bundle()

    monkeypatch.setattr(current, "load_bundle", slow_load)
    warm = current.warm_in_background()
    assert warm is not None
    assert started.wait(2.0)
    results: list[dict] = []
    read = lambda: results.append(current.latest_bodies("pack"))  # noqa: E731
    readers = [threading.Thread(target=read) for _ in range(3)]
    for t in readers:
        t.start()
    for t in [warm, *readers]:
        t.join(5.0)
    assert results == [{"p1": {"slug": "p1", "name": "Pack one"}}] * 3
    assert len(calls) == 1


def test_a_failed_read_serves_none_for_a_while_then_the_files_are_read_again(monkeypatch, caplog):
    calls = []
    now = [1000.0]

    def failing(root: Path) -> Bundle:
        calls.append(root)
        if len(calls) == 1:
            raise LoadError("packs/p1/pack.yaml: cannot parse")
        return _bundle()

    monkeypatch.setattr(current, "load_bundle", failing)
    monkeypatch.setattr(current.time, "monotonic", lambda: now[0])
    warm = current.warm_in_background()
    assert warm is not None
    warm.join(5.0)
    assert len(calls) == 1
    assert caplog.text.count("could not be read") == 1
    # Within the hold, requests are served none without another read or another warning.
    now[0] += current.FAILED_READ_HOLD_S - 1
    assert current.latest_bodies("pack") == {}
    assert current.latest_bodies("pack") == {}
    assert len(calls) == 1
    assert caplog.text.count("could not be read") == 1
    # Once it has passed, the next request reads again and the files serve from then on.
    now[0] += 1
    assert current.latest_bodies("pack") == {"p1": {"slug": "p1", "name": "Pack one"}}
    assert current.latest_bodies("pack") == {"p1": {"slug": "p1", "name": "Pack one"}}
    assert len(calls) == 2


def test_with_the_runtime_on_there_is_nothing_to_warm(monkeypatch):
    monkeypatch.setenv("NM_RUNTIME", "temporal")
    monkeypatch.setattr(current, "load_bundle", lambda root: pytest.fail("the files are not read"))
    assert current.warm_in_background() is None
    current.warm()


def test_startup_warms_the_files_without_waiting_for_the_read(monkeypatch):
    calls = []
    reading = threading.Event()
    release = threading.Event()

    def blocking_load(root: Path) -> Bundle:
        calls.append(root)
        reading.set()
        release.wait(5.0)
        return _bundle()

    monkeypatch.setattr(current, "load_bundle", blocking_load)
    with TestClient(create_app()) as client:
        # Startup completed (the client is serving) while the read still waits on `release`.
        assert client.get("/healthz").status_code == 200
        assert reading.wait(2.0)
        release.set()
        assert client.get("/v1/workflow-packs").status_code == 200
    assert len(calls) == 1
