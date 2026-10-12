"""In-memory demo state, loaded from fixtures. Replaced by Postgres + Temporal in the dynamic backend."""

import json
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

from app.models.catalog import Agent, Pack
from app.models.ops import (
    AuditEntry,
    AuditTargetType,
    BillingSummary,
    ConnectorEntry,
    Guardrail,
    Incident,
    OpsRun,
    OpsTeamMember,
    PackHistoryEntry,
    PackListing,
    PackListingSeed,
    Reviewer,
    ServiceStatus,
    Tenant,
    TenantSeed,
    TenantSeedDetail,
    TenantStatus,
    Toolkit,
)
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

if TYPE_CHECKING:
    from app.auth import OpsActor

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
    # Operator console. `tenant_details` holds the seeded detail lists of tenants other than the demo one.
    tenants: dict[str, Tenant]
    tenant_details: dict[str, TenantSeedDetail]
    audit_log: list[AuditEntry]  # oldest first
    ops_team: list[OpsTeamMember]
    pack_listings: dict[str, PackListing]
    pack_history: dict[str, list[PackHistoryEntry]]
    connector_catalog: dict[str, ConnectorEntry]
    toolkits: list[Toolkit]
    reviewers: dict[str, Reviewer]
    ops_runs: list[OpsRun]  # runs of tenants other than the demo one
    guardrails: dict[str, Guardrail]
    billing: BillingSummary
    services: dict[str, ServiceStatus]
    incidents: list[Incident]
    next_audit: int = 1
    next_incident: int = 1
    # Internal, never on the wire: the status a suspended tenant returns to on reactivation.
    status_before_suspension: dict[str, TenantStatus] = field(default_factory=dict)
    idempotency: OrderedDict[str, tuple[str, Any]] = field(default_factory=OrderedDict)
    next_run: int = 1048
    next_token: int = 8
    # Sync routes run in Starlette's threadpool, so handlers run in parallel. Every check-and-set on this
    # state holds this lock (see `locked_store`). Reentrant, because idempotent creates nest a mutation.
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def audit(
        self,
        actor: OpsActor,
        action: str,
        target_type: AuditTargetType,
        target_id: str,
        reason: str,
        summary: str,
    ) -> AuditEntry:
        """Record an operator mutation. Call it inside the same `locked_store()` block as the change, so the
        change and its entry land together."""
        if not self.lock._is_owned():  # type: ignore[attr-defined]
            raise RuntimeError("Store.audit must be called inside locked_store().")
        entry = AuditEntry(
            id=f"aud_{self.next_audit:04d}",
            at=utc_now(),
            actor_email=actor.email,
            actor_role=actor.role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            summary=summary,
        )
        self.next_audit += 1
        self.audit_log.append(entry)
        return entry


def iso(moment: datetime) -> str:
    """A UTC timestamp in the fixtures' style, for example 2026-10-12T16:40:00Z."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> str:
    return iso(datetime.now(UTC))


def _build() -> Store:
    runs = {r.id: r for r in _load("runs", list[Run])}
    older = _load("older_runs", list[RunSummary])
    summaries = sorted(
        [r.summary_row() for r in runs.values()] + older, key=lambda r: r.started_at, reverse=True
    )
    seeds = [
        (Tenant.model_validate(seed.model_dump(exclude={"detail"})), seed.detail)
        for seed in _load("ops_tenants", list[TenantSeed])
    ]
    pack_seeds = _load("ops_packs", list[PackListingSeed])
    packs = _load("packs", list[Pack])
    packs += [seed.pack for seed in pack_seeds if seed.pack is not None]
    incidents = _load("ops_incidents", list[Incident])
    audit_log = sorted(_load("ops_audit", list[AuditEntry]), key=lambda e: e.at)
    return Store(
        agents=_load("agents", list[Agent]),
        packs=packs,
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
        tenants={t.id: t for t, _ in seeds},
        tenant_details={t.id: detail for t, detail in seeds if detail is not None},
        audit_log=audit_log,
        ops_team=_load("ops_team", list[OpsTeamMember]),
        pack_listings={
            seed.slug: PackListing.model_validate(seed.model_dump(exclude={"history", "pack"}))
            for seed in pack_seeds
        },
        pack_history={seed.slug: list(seed.history) for seed in pack_seeds},
        connector_catalog={c.id: c for c in _load("ops_connectors", list[ConnectorEntry])},
        toolkits=_load("ops_toolkits", list[Toolkit]),
        reviewers={r.id: r for r in _load("ops_reviewers", list[Reviewer])},
        ops_runs=_load("ops_runs", list[OpsRun]),
        guardrails={g.key: g for g in _load("ops_guardrails", list[Guardrail])},
        billing=_load("ops_billing", BillingSummary),
        services={x.key: x for x in _load("ops_services", list[ServiceStatus])},
        incidents=incidents,
        next_audit=len(audit_log) + 1,
        next_incident=max(int(i.id.removeprefix("inc_")) for i in incidents) + 1,
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
