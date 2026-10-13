"""Persisted ops state of the live workspace: connector settings, platform switches and the ops audit log.

Each function takes an open psycopg connection and leaves the commit to the caller, so a change and its
audit entry land in one transaction. A connector without a `connector_settings` row is enabled with its
definition's defaults; Postgres overrides only where a row exists. Writes take a transaction-scoped
advisory lock on what they change, so two concurrent writers cannot both see the old state.
"""

from typing import Any, get_args

from psycopg.types.json import Jsonb

from app.defs import registry
from app.models.ops import AuditEntry, AuditTargetType, OpsRole
from app.store import iso

PAUSE_ALL_RUNS = "pause_all_runs"
# The operator's role is kept in `ops_audit.data` under this key (the table has no role column).
ACTOR_ROLE_KEY = "actor_role"
# Live writes are made by writers (owner or admin); an entry recorded without a known role reads as admin.
DEFAULT_AUDIT_ROLE: OpsRole = "admin"
OPS_ROLES = frozenset(get_args(OpsRole))
# Who set a platform switch that nobody changed yet: the default row 006_ops_state.sql seeds.
SYSTEM = "system"
ENABLED = "enabled"
DISABLED = "disabled"
VERBS = {ENABLED: "enable", DISABLED: "disable"}
ACTION_CLASSES = ("read", "write", "delete", "money")


class NoChange(Exception):
    """The requested state is already the current one; nothing was written."""


class UnknownConnector(LookupError):
    """No connector definition has this key."""


def _lock(conn, name: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ops_state:{name}",))


def _onoff(flag: bool) -> str:
    return "on" if flag else "off"


# --- audit ----------------------------------------------------------------------------------------------


def audit(
    conn,
    actor_email: str,
    action: str,
    target_type: AuditTargetType,
    target_id: str,
    reason: str,
    data: dict | None = None,
    *,
    actor_role: OpsRole | None = None,
) -> None:
    """Record one ops write. `data` holds the details, for example {"summary"}; the actor's role is stored
    in it under ACTOR_ROLE_KEY."""
    details = {**(data or {}), **({ACTOR_ROLE_KEY: actor_role} if actor_role else {})}
    conn.execute(
        "INSERT INTO ops_audit (actor_email, action, target_type, target_id, reason, data) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (actor_email, action, target_type, target_id, reason, Jsonb(details)),
    )


def list_audit(
    conn, limit: int = 50, *, target_type: AuditTargetType | None = None, target_id: str | None = None
) -> list[dict]:
    """Newest first; entries written at the same moment keep their write order, newest first."""
    return conn.execute(
        "SELECT id, at, actor_email, action, target_type, target_id, reason, data FROM ops_audit "
        "WHERE (%(type)s::text IS NULL OR target_type = %(type)s) "
        "AND (%(id)s::text IS NULL OR target_id = %(id)s) "
        "ORDER BY at DESC, id DESC LIMIT %(limit)s",
        {"type": target_type, "id": target_id, "limit": limit},
    ).fetchall()


def audit_entry(row: dict) -> AuditEntry:
    """An `ops_audit` row (`list_audit`) as the console's audit entry."""
    data = row["data"] or {}
    role = data.get(ACTOR_ROLE_KEY)
    return AuditEntry(
        id=f"aud_{row['id']}",
        at=iso(row["at"]),
        actor_email=row["actor_email"],
        actor_role=role if role in OPS_ROLES else DEFAULT_AUDIT_ROLE,
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        reason=row["reason"],
        summary=str(data.get("summary") or ""),
    )


# --- connectors -----------------------------------------------------------------------------------------


def connector_settings(conn) -> dict[str, dict]:
    """{connector key: {"status", "defaults"}} for every connector Ops changed; defaults None = the
    definition's."""
    rows = conn.execute("SELECT connector_key, status, defaults FROM connector_settings").fetchall()
    return {r["connector_key"]: {"status": r["status"], "defaults": r["defaults"]} for r in rows}


def effective_settings(definition: dict, row: dict | None) -> dict[str, Any]:
    """{"status", "defaults"} in force for a connector definition body and its `connector_settings` row
    (None when Ops changed nothing): the row where it says so, else enabled with the definition's defaults."""
    declared = definition.get("defaults") or {}
    defaults = {c: declared.get(c) for c in ACTION_CLASSES}
    if row is None:
        return {"status": ENABLED, "defaults": defaults}
    return {"status": row["status"], "defaults": row["defaults"] or defaults}


def _effective(conn, key: str, row: dict | None) -> dict[str, Any] | None:
    version = registry.latest(conn, "connector", key)
    return None if version is None else effective_settings(version.body, row)


def effective_connector(conn, key: str) -> dict[str, Any] | None:
    """{"status", "defaults"} in force for a connector: its row, else enabled with the definition's
    defaults. None when no connector definition has the key."""
    row = conn.execute(
        "SELECT status, defaults FROM connector_settings WHERE connector_key = %s", (key,)
    ).fetchone()
    return _effective(conn, key, row)


def _current(conn, key: str) -> dict[str, Any]:
    _lock(conn, f"connector:{key}")
    current = effective_connector(conn, key)
    if current is None:
        raise UnknownConnector(key)
    return current


def set_connector_status(
    conn, key: str, status: str, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> None:
    """Enable or disable a connector and audit it. NoChange when it already has that status."""
    before = _current(conn, key)["status"]
    if before == status:
        raise NoChange(f"{key} is already {status}.")
    conn.execute(
        "INSERT INTO connector_settings (connector_key, status, updated_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (connector_key) DO UPDATE SET status = EXCLUDED.status, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()",
        (key, status, actor_email),
    )
    data = {"summary": f"Status {before} → {status}", "before": before, "after": status}
    action = f"connector.{VERBS[status]}"
    audit(conn, actor_email, action, "connector", key, reason, data, actor_role=actor_role)


def set_connector_defaults(
    conn, key: str, defaults: dict, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> None:
    """Set a connector's action-class defaults and audit the change. NoChange when they are already in
    force."""
    before = _current(conn, key)["defaults"]
    after = {c: defaults[c] for c in ACTION_CLASSES}
    if after == before:
        raise NoChange(f"{key} already has these defaults.")
    conn.execute(
        "INSERT INTO connector_settings (connector_key, defaults, updated_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (connector_key) DO UPDATE SET defaults = EXCLUDED.defaults, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()",
        (key, Jsonb(after), actor_email),
    )
    changes = [f"{c} {before.get(c)} → {after[c]}" for c in ACTION_CLASSES if before.get(c) != after[c]]
    data = {"summary": "; ".join(changes), "before": before, "after": after}
    action = "connector.set_defaults"
    audit(conn, actor_email, action, "connector", key, reason, data, actor_role=actor_role)


def snapshot_policy(conn, connector_keys: list[str]) -> tuple[dict, list[str]]:
    """(overrides, disabled) to pin into a run snapshot, in the shape `real_runs.ops_connector_policy`
    returns: overrides = the action-class defaults in force by connector key; disabled = the keys Ops has
    disabled. A key without a connector definition is left out."""
    rows = connector_settings(conn)
    overrides, disabled = {}, []
    for key in sorted(connector_keys):
        current = _effective(conn, key, rows.get(key))
        if current is None:
            continue
        overrides[key] = current["defaults"]
        if current["status"] == DISABLED:
            disabled.append(key)
    return overrides, disabled


# --- platform switches ----------------------------------------------------------------------------------


def platform_setting(conn, key: str) -> dict | None:
    """The row of a platform switch ({value, updated_by, updated_at}), or None when there is none."""
    return conn.execute(
        "SELECT value, updated_by, updated_at FROM platform_settings WHERE key = %s", (key,)
    ).fetchone()


def pause_setting(conn) -> dict:
    """The pause switch's row. 006_ops_state.sql seeds it (off, set by "system"); should it be missing, the
    same default row is written back first. The caller commits."""
    conn.execute(
        "INSERT INTO platform_settings (key, value, updated_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (PAUSE_ALL_RUNS, Jsonb({"enabled": False}), SYSTEM),
    )
    row = platform_setting(conn, PAUSE_ALL_RUNS)
    if row is None:  # cannot happen: the row was just inserted or already existed
        raise RuntimeError("The pause switch has no row.")
    return row


def is_paused(conn) -> bool:
    """Whether Ops has paused every new run. No row means off."""
    row = platform_setting(conn, PAUSE_ALL_RUNS)
    return bool(row and (row["value"] or {}).get("enabled") is True)


def set_paused(
    conn, enabled: bool, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> None:
    """Turn the pause on or off and audit it as `guardrail.set`. NoChange when it already is."""
    _lock(conn, f"platform:{PAUSE_ALL_RUNS}")
    before = is_paused(conn)
    if before == enabled:
        raise NoChange(f"{PAUSE_ALL_RUNS} is already {_onoff(enabled)}.")
    conn.execute(
        "INSERT INTO platform_settings (key, value, updated_by) VALUES (%s, %s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()",
        (PAUSE_ALL_RUNS, Jsonb({"enabled": enabled}), actor_email),
    )
    data = {"summary": f"Enabled {_onoff(before)} → {_onoff(enabled)}", "before": before, "after": enabled}
    audit(
        conn, actor_email, "guardrail.set", "guardrail", PAUSE_ALL_RUNS, reason, data, actor_role=actor_role
    )
