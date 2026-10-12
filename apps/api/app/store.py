"""In-memory demo state, loaded from fixtures. Replaced by Postgres + Temporal in the dynamic backend."""

import json
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.models.catalog import Agent, Pack
from app.models.org import (
    AttentionItem,
    Connection,
    LedgerTxn,
    McpToken,
    Member,
    MemoryItem,
    Organization,
    Policy,
)
from app.models.runs import Run, RunSummary
from app.models.work import Approval, Earning, HumanTask

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str, kind: Any) -> Any:
    """Fixtures are strict: an unknown key is a typo and fails, although response models ignore extras."""
    raw = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    return TypeAdapter(kind).validate_python(raw, extra="forbid")


@dataclass
class Store:
    agents: list[Agent]
    packs: list[Pack]
    runs: dict[str, Run]
    run_summaries: list[RunSummary]
    tasks: dict[str, HumanTask]
    approvals: list[Approval]
    connections: list[Connection]
    memory: list[MemoryItem]
    ledger: list[LedgerTxn]
    earnings: list[Earning]
    tokens: list[McpToken]
    members: list[Member]
    policies: list[Policy]
    org: Organization
    attention: list[AttentionItem]
    idempotency: OrderedDict[str, tuple[str, Any]] = field(default_factory=OrderedDict)
    next_run: int = 1048
    next_token: int = 8
    # Sync routes run in Starlette's threadpool, so handlers run in parallel. Every check-and-set on this
    # state holds this lock (see `locked_store`). Reentrant, because idempotent creates nest a mutation.
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)


def _build() -> Store:
    runs = {r.id: r for r in _load("runs", list[Run])}
    older = _load("older_runs", list[RunSummary])
    summaries = sorted(
        [r.summary_row() for r in runs.values()] + older, key=lambda r: r.started_at, reverse=True
    )
    return Store(
        agents=_load("agents", list[Agent]),
        packs=_load("packs", list[Pack]),
        runs=runs,
        run_summaries=summaries,
        tasks={t.id: t for t in _load("human_tasks", list[HumanTask])},
        approvals=_load("approvals", list[Approval]),
        connections=_load("connections", list[Connection]),
        memory=_load("memory", list[MemoryItem]),
        ledger=_load("ledger", list[LedgerTxn]),
        earnings=_load("earnings", list[Earning]),
        tokens=_load("tokens", list[McpToken]),
        members=_load("members", list[Member]),
        policies=_load("policies", list[Policy]),
        org=_load("org", Organization),
        attention=_load("attention", list[AttentionItem]),
    )


_store: Store | None = None
_init_lock = threading.Lock()


def get_store() -> Store:
    global _store
    if _store is None:
        with _init_lock:
            if _store is None:
                _store = _build()
    return _store


@contextmanager
def locked_store() -> Iterator[Store]:
    """Hold the store lock for a whole check-and-set, so parallel requests cannot interleave."""
    store = get_store()
    with store.lock:
        yield store


def reset_store() -> Store:
    global _store
    with _init_lock:
        _store = _build()
    return _store
