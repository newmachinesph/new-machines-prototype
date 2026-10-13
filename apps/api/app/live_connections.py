"""App connections in the live workspace: the connector definitions the org's hired packs need, merged with
the org's `connections` rows. Connecting is sandbox only for now (per-user Composio accounts come later).
Every query is scoped to one org."""

from psycopg.types.json import Jsonb

from app import db, settings
from app.catalog.packs import SandboxForecast
from app.defs.current import latest_bodies
from app.errors import ApiProblem
from app.models.org import Connection, Grant

# connections.status values of a connected app. A sandbox connection lets a run use the app only while its
# calls would run on sandbox data in the current connector mode (see `missing_apps`).
USABLE = frozenset({"connected", "sandbox"})
SANDBOX_ACCOUNT = "Sandbox data"
LIVE_UNAVAILABLE = "Live app connections are not available yet"


def _resolve(connectors: dict[str, dict], name: str) -> str:
    """The connector key `name` refers to: a key, or an app's display name (any case). 404 otherwise."""
    if name in connectors:
        return name
    folded = name.casefold()
    found = next(
        (k for k, b in sorted(connectors.items()) if str(b.get("app") or "").casefold() == folded), None
    )
    if found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No app called {name}.")
    return found


def app_name(connectors: dict[str, dict], key: str) -> str:
    return str((connectors.get(key) or {}).get("app") or key)


def _access(action_class: str, defaults: dict) -> str:
    """What a tool's action class may do under the connector's defaults, as a grant's access."""
    if action_class == "read":
        return "read"
    verdict = defaults.get(action_class)
    if verdict == "permit":
        return "write"
    return "write (approval)" if verdict == "require_approval" else "denied"


def contract_capabilities(pack: dict, contracts: dict[str, dict]) -> set[str] | None:
    """The tool capabilities the pack's Work Contract grants; None when its contract is unknown."""
    contract = contracts.get(str(pack.get("contract") or ""))
    if not isinstance(contract, dict):
        return None
    return {str(c) for c in (contract.get("authorization") or {}).get("tool_capabilities") or []}


def pack_grants(connector: dict, pack_name: str, capabilities: set[str] | None = None) -> list[dict]:
    """One grant per capability of the connector's tools, for the hired pack `pack_name`. With
    `capabilities` (the pack contract's), only the tools the pack may use: one connector can serve packs
    that use different tools of it."""
    defaults = connector.get("defaults") if isinstance(connector.get("defaults"), dict) else {}
    grants: dict[str, dict] = {}
    for tool in connector.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("capability"):
            continue
        capability = str(tool["capability"])
        if capabilities is not None and capability not in capabilities:
            continue
        grants.setdefault(
            capability,
            {
                "install": pack_name,
                "capability": capability,
                "access": _access(str(tool.get("action_class") or ""), defaults),
            },
        )
    return list(grants.values())


def _pack_bodies() -> dict[str, dict]:
    """Latest pack definition bodies by slug. Read before taking a connection: latest_bodies uses its own,
    and holding two pooled connections per request can exhaust the pool under load."""
    return {str(b.get("slug") or k): b for k, b in latest_bodies("pack").items()}


def _hired_packs(conn, org_id: str, packs: dict[str, dict]) -> list[dict]:
    """The pack definition bodies of the org's hired packs, oldest hire first."""
    rows = conn.execute(
        "SELECT pack_slug FROM installations WHERE org_id = %s ORDER BY installed_at, pack_slug", (org_id,)
    ).fetchall()
    return [packs[r["pack_slug"]] for r in rows if r["pack_slug"] in packs]


def _grants_for(
    connectors: dict[str, dict], key: str, packs: list[dict], contracts: dict[str, dict]
) -> list[dict]:
    return [
        g
        for pack in packs
        if key in (pack.get("connectors") or [])
        for g in pack_grants(
            connectors.get(key) or {},
            str(pack.get("name") or pack.get("slug")),
            contract_capabilities(pack, contracts),
        )
    ]


def _connection(connectors: dict[str, dict], key: str, row: dict | None) -> Connection:
    mode = settings.connector_mode()
    if row is None or row["status"] not in USABLE | {"needs_reauth"}:
        return Connection(
            app=app_name(connectors, key),
            account="",
            status="not_connected",
            provider="Mock" if mode == "sandbox" else "Composio",
            oauth_scopes=[],
            grants=[],
            key=key,
            mode="sandbox" if mode == "sandbox" else "composio",
        )
    sandbox = row["mode"] == "sandbox"
    return Connection(
        app=app_name(connectors, key),
        account=SANDBOX_ACCOUNT if sandbox else "",
        status=row["status"],
        provider="Mock" if sandbox else "Composio",
        oauth_scopes=[],
        grants=[Grant.model_validate(g) for g in row["grants"] or []],
        key=key,
        mode=row["mode"],
    )


def _rows(conn, org_id: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT app, status, mode, grants FROM connections WHERE org_id = %s", (org_id,)
    ).fetchall()
    return {r["app"]: r for r in rows}


def list_connections(org_id: str) -> list[Connection]:
    """The connectors the org's hired packs use (first hire first), then any other app the org connected."""
    connectors, bodies = latest_bodies("connector"), _pack_bodies()
    with db.connect() as conn:
        packs = _hired_packs(conn, org_id, bodies)
        rows = _rows(conn, org_id)
    keys = list(dict.fromkeys(str(c) for p in packs for c in p.get("connectors") or []))
    keys += sorted(k for k, r in rows.items() if k not in keys and r["status"] in USABLE)
    return [_connection(connectors, k, rows.get(k)) for k in keys]


def connect(org_id: str, user_id: str, name: str) -> Connection:
    """Connect an app for the org. In sandbox connector mode the connection serves sandbox data, with a
    grant per capability for each hired pack that uses it; live and auto modes are not available yet."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    if settings.connector_mode() != "sandbox":
        raise ApiProblem(409, "LIVE_CONNECT_UNAVAILABLE", f"{LIVE_UNAVAILABLE}.")
    bodies, contracts = _pack_bodies(), latest_bodies("contract")
    with db.connect() as conn:
        grants = _grants_for(connectors, key, _hired_packs(conn, org_id, bodies), contracts)
        conn.execute(
            "INSERT INTO connections (org_id, app, status, mode, grants, connected_by) "
            "VALUES (%s, %s, 'sandbox', 'sandbox', %s, %s) ON CONFLICT (org_id, app) DO UPDATE SET "
            "status = 'sandbox', mode = 'sandbox', grants = EXCLUDED.grants, "
            "connected_by = EXCLUDED.connected_by, connected_at = now()",
            (org_id, key, Jsonb(grants), user_id),
        )
        row = _rows(conn, org_id)[key]
        conn.commit()
    return _connection(connectors, key, row)


def disconnect(org_id: str, name: str) -> Connection:
    """The org's app is no longer connected and holds no grants (idempotent)."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    with db.connect() as conn:
        conn.execute(
            "UPDATE connections SET status = 'not_connected', grants = '[]'::jsonb "
            "WHERE org_id = %s AND app = %s",
            (org_id, key),
        )
        row = _rows(conn, org_id).get(key)
        conn.commit()
    return _connection(connectors, key, row)


def revoke_grant(org_id: str, name: str, install: str, capability: str) -> None:
    """Remove one grant from the org's connection; 404 when it holds no such grant."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT grants FROM connections WHERE org_id = %s AND app = %s FOR UPDATE", (org_id, key)
        ).fetchone()
        grants = list(row["grants"] or []) if row else []
        kept = [g for g in grants if not (g.get("install") == install and g.get("capability") == capability)]
        if len(kept) == len(grants):
            raise ApiProblem(404, "NOT_FOUND", "No such grant.")
        conn.execute(
            "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s", (Jsonb(kept), org_id, key)
        )
        conn.commit()


def grant_pack(
    conn, connectors: dict[str, dict], org_id: str, pack: dict, contracts: dict[str, dict]
) -> None:
    """A pack was hired: the org's apps it uses that are already connected gain its grants (those it holds
    already are left as they are). Runs on the caller's connection and does not commit."""
    name = str(pack.get("name") or pack.get("slug"))
    capabilities = contract_capabilities(pack, contracts)
    for key in [str(c) for c in pack.get("connectors") or []]:
        row = conn.execute(
            "SELECT grants, status FROM connections WHERE org_id = %s AND app = %s FOR UPDATE", (org_id, key)
        ).fetchone()
        if row is None or row["status"] not in USABLE:
            continue
        grants = list(row["grants"] or [])
        held = {(g.get("install"), g.get("capability")) for g in grants}
        added = [
            g
            for g in pack_grants(connectors.get(key) or {}, name, capabilities)
            if (name, g["capability"]) not in held
        ]
        if added:
            conn.execute(
                "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s",
                (Jsonb(grants + added), org_id, key),
            )


def _usable_now(key: str, row: dict | None, connectors: dict[str, dict], sandboxed: SandboxForecast) -> bool:
    """Whether a run may use the app now. A sandbox connection counts only when the worker would serve this
    connector's calls from sandbox data in the current mode (always in sandbox mode, never in live mode, in
    auto mode when the account is not connected), so the start gate and the worker agree."""
    status = (row or {}).get("status")
    if status == "connected":
        return True
    return status == "sandbox" and sandboxed(key, connectors.get(key) or {})


def missing_apps(org_id: str, connector_keys: list[str]) -> list[str]:
    """Display names of `connector_keys` the org has not connected in a way runs can use now."""
    connectors = latest_bodies("connector")
    with db.connect() as conn:
        rows = _rows(conn, org_id)
    sandboxed = SandboxForecast()
    return [
        app_name(connectors, k)
        for k in connector_keys
        if not _usable_now(k, rows.get(k), connectors, sandboxed)
    ]
