"""Replay a recorded PackRunner history against the current workflow code.

A change to the graph walk that would send in-flight runs down a different path (new or reordered activity
calls, timers or signals) fails here with a non-determinism error. Replay needs no database or server.

Re-record only when a change is meant to break replay (and in-flight runs can be drained first):

    NM_RECORD_HISTORY=1 uv run pytest tests/test_replay.py
"""

import asyncio
import gzip
import json
import os
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from app.worker.workflow import PackRunner
from tests.test_workflow import _drive, _new_run, _start, _waiting, runtime_env  # noqa: F401  (fixture)

# Gzipped: every activity input carries the pinned snapshot, so the JSON is about 0.8 MB.
HISTORY = Path(__file__).parent / "fixtures" / "histories" / "pack_runner_review_approval.json.gz"
RECORD = os.environ.get("NM_RECORD_HISTORY") == "1"


def _replay(path: Path) -> None:
    data = json.loads(gzip.decompress(path.read_bytes()))
    history = WorkflowHistory.from_json(data["workflow_id"], data["history"])
    asyncio.run(Replayer(workflows=[PackRunner]).replay_workflow(history))


@pytest.mark.skipif(RECORD, reason="re-recording")
def test_recorded_history_replays_on_the_current_workflow():
    _replay(HISTORY)


@pytest.mark.skipif(not RECORD, reason="set NM_RECORD_HISTORY=1 to re-record the history")
def test_record_history(runtime_env):  # noqa: F811
    """Fake provider, sandbox connectors: review resolved, write approved, run completed."""
    conn = runtime_env
    run_id, snapshot = _new_run(conn)

    async def scenario(env):
        handle = await _start(env.client, run_id, snapshot)
        review = await _waiting(handle, "review")
        await handle.signal(PackRunner.human_result, args=[review["task_id"], "resolved", "Checked."])
        approval = await _waiting(handle, "approve_write")
        await handle.signal(PackRunner.approval, args=[approval["task_id"], "granted", "buyer@demo"])
        assert await handle.result() == "COMPLETED"
        history = await handle.fetch_history()
        data = {"workflow_id": run_id, "history": json.loads(history.to_json())}
        return json.dumps(data, separators=(",", ":"))

    text = asyncio.run(_drive(None, scenario))
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_bytes(gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0))
    _replay(HISTORY)
