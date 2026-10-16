"""app.temporal_client without a Temporal server: timeouts cancel the call, connecting holds no lock."""

import asyncio
import threading

import pytest

from app import temporal_client


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(temporal_client, "CALL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(temporal_client, "_client", None)
    monkeypatch.setattr(temporal_client, "_connecting", None)


def test_a_call_that_times_out_is_cancelled(fresh):
    cancelled = threading.Event()

    async def slow() -> None:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(TimeoutError):
        temporal_client._wait(slow())
    assert cancelled.wait(timeout=2)  # the coroutine never completes later (no late workflow start)


def test_connecting_holds_no_lock_and_a_timed_out_connect_is_cancelled_and_retried(fresh, monkeypatch):
    seen: dict = {"locked": None, "cancelled": threading.Event()}

    async def slow_connect():
        await asyncio.sleep(0.05)  # get_client has scheduled this and left its critical section by now
        seen["locked"] = temporal_client._lock.locked()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            seen["cancelled"].set()
            raise

    monkeypatch.setattr(temporal_client, "connect", slow_connect)
    with pytest.raises(TimeoutError):
        temporal_client.get_client()
    assert seen["locked"] is False
    assert seen["cancelled"].wait(timeout=2)

    async def quick_connect():
        return "client"

    monkeypatch.setattr(temporal_client, "connect", quick_connect)
    assert temporal_client.get_client() == "client"
    assert temporal_client.get_client() == "client"


def test_workflow_id_is_the_bare_run_id_by_default(monkeypatch):
    monkeypatch.delenv("NM_WORKFLOW_ID_PREFIX", raising=False)
    assert temporal_client.workflow_id("run_42") == "run_42"


def test_workflow_id_carries_the_configured_prefix(monkeypatch):
    monkeypatch.setenv("NM_WORKFLOW_ID_PREFIX", "qa-c-")
    assert temporal_client.workflow_id("run_42") == "qa-c-run_42"


class _Client:
    """Records the workflow ids the API hands Temporal, and the payloads it sends."""

    def __init__(self):
        self.ids: list[str] = []
        self.args: list = []

    async def start_workflow(self, name, arg, *, id, task_queue):
        self.ids.append(id)
        self.args.append(arg)

    def get_workflow_handle(self, wid):
        client = self

        class Handle:
            async def signal(self, name, args=None):
                client.ids.append(wid)
                client.args.append(args)

            async def terminate(self, reason=""):
                client.ids.append(wid)

        return Handle()


def test_every_run_call_uses_the_prefixed_workflow_id(monkeypatch):
    monkeypatch.setenv("NM_WORKFLOW_ID_PREFIX", "qa-c-")
    client = _Client()
    monkeypatch.setattr(temporal_client, "get_client", lambda timeout=None: client)
    temporal_client.start_run("r1", {}, {})
    temporal_client.signal_human("r1", "t1", "resolved", "")
    temporal_client.signal_approval("r1", "t1", "granted", "me")
    temporal_client.terminate_run("r1", "why")
    assert client.ids == ["qa-c-r1"] * 4


def test_the_workflow_input_and_signals_carry_the_bare_run_id(monkeypatch):
    """Only Temporal's workflow id has the prefix: the worker records events against the run id itself."""
    monkeypatch.setenv("NM_WORKFLOW_ID_PREFIX", "qa-c-")
    client = _Client()
    monkeypatch.setattr(temporal_client, "get_client", lambda timeout=None: client)
    temporal_client.start_run("r1", {"s": 1}, {"i": 2})
    temporal_client.signal_human("r1", "t1", "resolved", "note")
    temporal_client.signal_approval("r1", "t2", "granted", "me")
    start, human, approval = client.args
    assert start.run_id == "r1"
    assert (start.snapshot, start.input) == ({"s": 1}, {"i": 2})
    assert human == ["t1", "resolved", "note", []]
    assert approval == ["t2", "granted", "me"]
    assert "qa-c-" not in repr(client.args)
