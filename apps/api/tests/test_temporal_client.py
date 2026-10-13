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
