"""App connections in the live workspace: the connector definitions the org's added packs need, merged with
the org's `connections` rows. Each connection keeps its own mode: sandbox data, or the org's own account
through Composio (`connect_live`, `sync`); NM_CONNECTOR_MODE does not decide here. Every query is scoped to
one org."""

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from psycopg.types.json import Jsonb

from app import composio_accounts, db, settings, workspace
from app.defs import owners, registry
from app.defs.current import latest_bodies
from app.errors import ApiProblem
from app.models.org import Connection, ConnectStarted, Grant, RevokedGrant
from app.runtime import routes

log = logging.getLogger(__name__)

# connections.status values that hold grants (`grant_pack`). Whether a run may use an app is its route
# (`routes.route_of`).
USABLE = frozenset({"connected", "sandbox"})
# Statuses whose grants a row keeps: `USABLE`, and a connected account that needs signing in again (`sync`
# keeps its grants until then, so a grant allowed again meanwhile must be kept too).
KEEPS_GRANTS = USABLE | {"needs_reauth"}
SANDBOX_ACCOUNT = "Sandbox data"
NO_LIVE_TOOLKIT = "NO_LIVE_TOOLKIT"
NOT_REMOVED = "sign_in_not_removed"
# Who may bind, replace or remove the org's own accounts, and change what packs may do with an app: the same
# roles that invite people. Other members connect simulated data and sync a sign-in an admin started.
REAL_ACCOUNT_ROLES = workspace.INVITER_ROLES
FORBIDDEN = "FORBIDDEN"


def require_real_account_role(role: str) -> None:
    """403 unless `role` may change the org's real accounts (`REAL_ACCOUNT_ROLES`)."""
    if role not in REAL_ACCOUNT_ROLES:
        raise ApiProblem(403, FORBIDDEN, "Only an owner or admin can change the org's real accounts.")


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


def contract_capabilities(pack: dict, contracts: dict[str, dict]) -> set[str]:
    """The tool capabilities the pack's Work Contract grants; none when its contract cannot be found (a pack
    whose contract is missing or not visible grants nothing, rather than every tool)."""
    contract = contracts.get(str(pack.get("contract") or ""))
    if not isinstance(contract, dict):
        return set()
    return {str(c) for c in (contract.get("authorization") or {}).get("tool_capabilities") or []}


def pack_grants(connector: dict, pack_name: str, capabilities: set[str] | None = None) -> list[dict]:
    """One grant per capability of the connector's tools, for the added pack `pack_name`. With
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


@dataclass(frozen=True)
class _Packs:
    """The pack definitions the org's grants come from: bodies and versions by slug, from one read."""

    bodies: dict[str, dict]
    versions: dict[str, int]
    # The listing version each added listed pack's installation held when read (`installations`).
    held: dict[str, str | None] = field(default_factory=dict)


def _foreign(conn, kind: str, key: str, org_id: str) -> bool:
    """Whether kind/key is another workspace's private definition: one the org sees only while it is
    listed."""
    owner = registry.owner_of(conn, kind, key)
    return owner.visibility == "private" and owner != owners.org_owner(org_id)


def _listed_bundle(conn, org_id: str, key: str, version: int) -> dict[tuple[str, str], int] | None:
    """The definitions, by (kind, key), of the approved version of pack `key`'s listing that the org's
    installation holds (`installations.listing_version_id`), when that version holds version `version` of the
    pack and the listing is listed by the pack's private owner (the rule of `registry.pinnable_version`); None
    otherwise, also when the installation holds no listing version (it fails closed). A version approved
    again at the same pack version changes nothing until the org updates."""
    row = conn.execute(
        "SELECT lv.definitions FROM listing_versions lv JOIN listings ls ON ls.id = lv.listing_id "
        "JOIN definition_owners o ON o.kind = 'pack' AND o.key = %(key)s AND o.owner_kind = 'org' "
        "AND o.owner_id = ls.publisher_org_id AND o.visibility = 'private' "
        "JOIN installations i ON i.org_id = %(org)s AND i.pack_slug = %(key)s "
        "AND lv.id = i.listing_version_id "
        "WHERE ls.kind = 'pack' AND ls.definition_key = %(key)s AND ls.status = 'listed' "
        "AND ls.publisher_org_id <> %(org)s AND lv.status = 'approved' AND lv.definitions @> %(ref)s",
        {"key": key, "org": org_id, "ref": Jsonb([{"kind": "pack", "key": key, "version": version}])},
    ).fetchone()
    if row is None:
        return None
    return {(str(d["kind"]), str(d["key"])): int(d["version"]) for d in row["definitions"]}


def pinned_contract(conn, org_id: str, pack: registry.Version) -> registry.Version | None:
    """The Work Contract the org's grants for `pack` (the version its installation pins) come from. Of
    another workspace's listed pack: the contract in the approved bundle that holds that pack version, so a
    newer approved version changes nothing until the org updates; None (it grants nothing) when no listed
    bundle holds it. Of the platform's packs and the org's own: the contract the org may see."""
    key = str(pack.body.get("contract") or "")
    if not _foreign(conn, "pack", pack.key, org_id):
        return registry.visible_version(conn, "contract", key, org_id)
    bundle = _listed_bundle(conn, org_id, pack.key, pack.version)
    if bundle is None:
        return None
    if ("contract", key) in bundle:
        return registry.pinnable_version(conn, "contract", key, bundle[("contract", key)], org_id)
    return (
        None
        if _foreign(conn, "contract", key, org_id)
        else registry.visible_version(conn, "contract", key, org_id)
    )


def _pinned(
    conn, org_id: str, latest: registry.Version, version: int
) -> tuple[registry.Version, dict] | None:
    """(pack at `version`, its contract body or None) of another workspace's listed pack the org pinned at
    `version`; None when the org may no longer pin it (it then grants nothing)."""
    pack = registry.pinnable_version(conn, "pack", latest.key, version, org_id)
    if pack is None:
        return None
    contract = pinned_contract(conn, org_id, pack)
    return pack, (contract.body if contract else None)


def _definitions(conn, org_id: str) -> tuple[_Packs, dict[str, dict]]:
    """(packs, contract bodies by key) the org's grants come from, read on `conn`: what the org may see,
    except that another workspace's listed pack the org added is read at the version its installation pins,
    with the contract of that version's approved bundle."""
    visible = registry.latest_visible(conn, org_id)
    packs = {str(v.body.get("slug") or v.key): v for v in visible if v.kind == "pack"}
    contracts = {v.key: v.body for v in visible if v.kind == "contract"}
    hires = conn.execute(
        "SELECT pack_slug, pack_version, listing_version_id FROM installations WHERE org_id = %s "
        "ORDER BY pack_slug",
        (org_id,),
    ).fetchall()
    held: dict[str, str | None] = {}
    for hire in hires:
        slug, latest = hire["pack_slug"], packs.get(hire["pack_slug"])
        if latest is None or not _foreign(conn, "pack", latest.key, org_id):
            continue
        held[slug] = hire["listing_version_id"]
        pinned = _pinned(conn, org_id, latest, int(hire["pack_version"]))
        contract_key = str(((pinned[0] if pinned else latest).body).get("contract") or "")
        if _foreign(conn, "contract", contract_key, org_id):
            contracts.pop(contract_key, None)  # never the newest approved contract of a pack pinned below it
        if pinned is None:
            packs.pop(slug)
            continue
        packs[slug] = pinned[0]
        if pinned[1] is not None:
            contracts[contract_key] = pinned[1]
    return (
        _Packs(
            bodies={slug: v.body for slug, v in packs.items()},
            versions={slug: v.version for slug, v in packs.items()},
            held=held,
        ),
        contracts,
    )


def added_names(conn, org_id: str) -> dict[str, str]:
    """{slug: name} of the packs the org added, the names its grants are keyed by: a listed pack under the
    name of the version its installation holds. A pack it has not added holds no grants. Read on `conn`."""
    packs, _ = _definitions(conn, org_id)
    added = conn.execute("SELECT pack_slug FROM installations WHERE org_id = %s", (org_id,)).fetchall()
    return {
        r["pack_slug"]: str(packs.bodies[r["pack_slug"]].get("name") or r["pack_slug"])
        for r in added
        if r["pack_slug"] in packs.bodies
    }


def _read_packs(org_id: str) -> tuple[_Packs, dict[str, dict]]:
    """The packs and contracts the org may see. Read before taking a connection: the read uses its own, and
    holding two pooled connections per request can exhaust the pool under load. `_fresh` tells, under the
    (org, app) lock, whether a save moved an added pack on since."""
    if not settings.runtime_enabled():  # the definition files: nothing saves between a read and a lock
        bodies = {str(b.get("slug") or k): b for k, b in latest_bodies("pack", org_id).items()}
        return _Packs(bodies, {}), latest_bodies("contract", org_id)
    with db.connect() as conn:
        return _definitions(conn, org_id)


def _pack_bodies(org_id: str) -> dict[str, dict]:
    """Latest pack definition bodies the org may see, by slug (`_read_packs`)."""
    return _read_packs(org_id)[0].bodies


def _fresh(
    conn, org_id: str, packs: _Packs, contracts: dict[str, dict]
) -> tuple[dict[str, dict], dict[str, dict]]:
    """(pack bodies, contracts) to compute grants from, under the (org, app) lock: the ones read before it,
    unless a save or an update moved one of the org's added packs past the version (or listing version) read
    (a rename in between would write grants under the old name); then both are read again, once, on
    `conn`."""
    rows = conn.execute(
        "SELECT pack_slug, pack_version, listing_version_id FROM installations WHERE org_id = %s", (org_id,)
    )
    moved = any(
        packs.versions.get(r["pack_slug"], 0) < r["pack_version"]
        or (r["pack_slug"] in packs.held and packs.held[r["pack_slug"]] != r["listing_version_id"])
        for r in rows.fetchall()
    )
    if not moved:
        return packs.bodies, contracts
    again, contracts = _definitions(conn, org_id)
    return again.bodies, contracts


def _added_packs(conn, org_id: str, packs: dict[str, dict]) -> list[dict]:
    """The pack definition bodies of the packs the org added, oldest first."""
    rows = conn.execute(
        "SELECT pack_slug FROM installations WHERE org_id = %s ORDER BY installed_at, pack_slug", (org_id,)
    ).fetchall()
    return [packs[r["pack_slug"]] for r in rows if r["pack_slug"] in packs]


def _revoked_keys(revoked: list[dict] | None) -> set[tuple[str, str]]:
    """The (install, capability) pairs a person revoked on a connection (`revoked_grants`). An entry that is
    not a dict with both values as non-empty strings is skipped everywhere."""
    return {
        (r["install"], r["capability"])
        for r in revoked or []
        if isinstance(r, dict)
        and all(isinstance(r.get(f), str) and r.get(f) for f in ("install", "capability"))
    }


def _grants_for(
    connectors: dict[str, dict],
    key: str,
    packs: list[dict],
    contracts: dict[str, dict],
    revoked: list[dict] | None = None,
) -> list[dict]:
    """The grants the org's connection to `key` holds when recomputed: one per capability for each pack the
    org added that uses it, minus the ones a person revoked. Nothing that recomputes grants brings a revoked
    one back."""
    gone = _revoked_keys(revoked)
    return [
        g
        for pack in packs
        if key in (pack.get("connectors") or [])
        for g in pack_grants(
            connectors.get(key) or {},
            str(pack.get("name") or pack.get("slug")),
            contract_capabilities(pack, contracts),
        )
        if (g["install"], g["capability"]) not in gone
    ]


def grants_for(
    conn,
    connectors: dict[str, dict],
    bodies: dict[str, dict],
    contracts: dict[str, dict],
    org_id: str,
    key: str,
) -> list[dict]:
    """`_grants_for` for the org's connection to `key` as it is now, for every place that recomputes grants
    after the row exists (the sync that finds a real account ACTIVE). `bodies` and `contracts` are read by
    the caller before it takes `conn` (`_read_packs`: the definition readers use their own pooled connections)
    and checked under its lock (`_fresh`). Reads the org's packs and the row's revoked grants on `conn`,
    without committing."""
    row = conn.execute(
        "SELECT revoked_grants FROM connections WHERE org_id = %s AND app = %s", (org_id, key)
    ).fetchone()
    packs = _added_packs(conn, org_id, bodies)
    return _grants_for(connectors, key, packs, contracts, row["revoked_grants"] if row else None)


def _lock(conn, org_id: str, key: str) -> None:
    """Serialise changes to the org's row for an app (connect, sync, sweep, disconnect, revoke, re-grant, and
    the grants an added or saved pack writes) for the rest of the transaction: two connects at once would
    each store an account for the same row, and the others read the row and write it back. The grant changes
    also lock the row itself (FOR UPDATE)."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{org_id}:{key}",))


def shown_status(org_id: str, row: dict[str, Any]) -> str:
    """The row's status as the web and the ops console show it. A connected or sandbox row that a run would
    reach nothing through (`routes.route_of`: a Composio row without its account, a status that does not
    match its mode) needs signing in again, so every list agrees with the start gate and the marketplace
    labels. `row` has status, mode and account_id."""
    status = str(row["status"])
    if status in USABLE and routes.route_of(org_id, row).mode == "none":
        return "needs_reauth"
    return status


def _revoked(row: dict | None) -> list[RevokedGrant]:
    """The grants a person revoked on the row, as the web lists them: the same pairs `_revoked_keys` reads
    from `revoked_grants` (so a malformed entry is skipped, not a 500 for the whole list), sorted."""
    pairs = sorted(_revoked_keys((row or {}).get("revoked_grants")))
    return [RevokedGrant(install=install, capability=capability) for install, capability in pairs]


def _connection(connectors: dict[str, dict], key: str, row: dict | None, org_id: str) -> Connection:
    """The org's connection to one app as the web shows it. No row, or a disconnected one, is not connected
    and has no mode; any other row reports its own mode and status (`shown_status`). Every row lists what a
    person revoked on it, a disconnected one too: the revocation outlives the connection. A disconnected row
    that still holds a Composio account (a disconnect or a sign-in that did not finish could not remove it
    at Composio) carries the `NOT_REMOVED` notice, in every list, until a connect or disconnect removes
    the account."""
    name = app_name(connectors, key)
    if row is None or row["status"] == "not_connected":
        return Connection(
            app=name,
            account="",
            status="not_connected",
            provider="Mock",
            oauth_scopes=[],
            grants=[],
            revoked=_revoked(row),
            key=key,
            notice=NOT_REMOVED if row is not None and row["account_id"] else None,
        )
    sandbox = row["mode"] == "sandbox"
    return Connection(
        app=name,
        account=SANDBOX_ACCOUNT if sandbox else "",
        status=shown_status(org_id, row),
        provider="Mock" if sandbox else "Composio",
        oauth_scopes=[],
        grants=[Grant.model_validate(g) for g in row["grants"] or []],
        revoked=_revoked(row),
        key=key,
        mode=row["mode"],
    )


def _rows(conn, org_id: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT app, status, mode, grants, account_id, revoked_grants FROM connections WHERE org_id = %s",
        (org_id,),
    ).fetchall()
    return {r["app"]: r for r in rows}


def list_connections(org_id: str) -> list[Connection]:
    """The connectors the org's added packs use (first added first), then any other app the org has a
    connection to (connected, pending or needing sign-in again)."""
    connectors, bodies = latest_bodies("connector"), _pack_bodies(org_id)
    with db.connect() as conn:
        packs = _added_packs(conn, org_id, bodies)
        rows = _rows(conn, org_id)
    keys = list(dict.fromkeys(str(c) for p in packs for c in p.get("connectors") or []))
    keys += sorted(k for k, r in rows.items() if k not in keys and r["status"] != "not_connected")
    return [_connection(connectors, k, rows.get(k), org_id) for k in keys]


def connect_sandbox(org_id: str, user_id: str, name: str, role: str) -> Connection:
    """Connect an app to sandbox data, with a grant per capability for each added pack that uses it. Works in
    any connector mode: the connection itself says runs use sandbox data. Over a row connected to the org's
    own account (mode composio, not `not_connected`) this replaces that account and retires it at Composio,
    so it is only for `role` in `REAL_ACCOUNT_ROLES` (403 otherwise, checked under the lock); an app not
    connected, already on sandbox data, or a not-connected composio row that still holds a leftover account
    (retiring it is cleanup) is any member's to connect."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    read, contracts = _read_packs(org_id)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        bodies, contracts = _fresh(conn, org_id, read, contracts)
        current = _rows(conn, org_id).get(key) or {}
        if current.get("mode") == "composio" and current.get("status") != "not_connected":
            require_real_account_role(role)
        held = current.get("account_id")
        packs = _added_packs(conn, org_id, bodies)
        grants = _grants_for(connectors, key, packs, contracts, current.get("revoked_grants"))
        conn.execute(
            "INSERT INTO connections (org_id, app, status, mode, grants, connected_by) "
            "VALUES (%s, %s, 'sandbox', 'sandbox', %s, %s) ON CONFLICT (org_id, app) DO UPDATE SET "
            "status = 'sandbox', mode = 'sandbox', grants = EXCLUDED.grants, "
            "connected_by = EXCLUDED.connected_by, connected_at = now()",
            (org_id, key, Jsonb(grants), user_id),
        )
        row = _rows(conn, org_id)[key]
        conn.commit()
    _retire(org_id, key, held)
    return _connection(connectors, key, row, org_id)


def _callback_url(key: str) -> str:
    return f"{settings.web_origin()}/app/connections?{urlencode({'connected': key})}"


def _retire(org_id: str, key: str, account_id: str | None) -> None:
    """Remove the account the org's row still holds after it switched to sandbox data, then forget it. Best
    effort: when the removal fails the id stays on the row, and the next connect retries it (a sandbox connect
    here; a live connect before it makes its new link). When only the bookkeeping fails, the id stays too and
    the retry finds the account gone at Composio, which counts as removed."""
    if not account_id:
        return
    try:
        composio_accounts.remove(account_id)
    except ApiProblem as problem:
        log.warning("Could not remove a retired Composio account of %s for %s: %s", key, org_id, problem.code)
        return
    try:
        with db.connect() as conn:
            conn.execute(
                "UPDATE connections SET account_id = NULL WHERE org_id = %s AND app = %s AND account_id = %s",
                (org_id, key, account_id),
            )
            conn.commit()
    except Exception as exc:
        log.warning(
            "Removed the Composio account %s of %s for %s but could not forget it: %s",
            account_id,
            key,
            org_id,
            type(exc).__name__,
        )


def _held_accounts(conn, org_id: str) -> set[str]:
    """The Composio account ids every connection of the org holds, whatever the app or status."""
    return {str(r["account_id"]) for r in _rows(conn, org_id).values() if r["account_id"]}


def _sweep(org_id: str, key: str, user_id: str, toolkit: str, started: str) -> None:
    """Remove every token-holding account the org's Composio user has for the app's toolkit that no
    connection of the org holds, nor `started` (the one just linked): what removals that failed earlier left
    behind. The held ids are read under the (org, app) lock, which is released before Composio is called, so
    no pooled connection waits on the network. The other connections' accounts are kept (two connectors can
    share one toolkit). A connect racing this one has a link in progress: INITIATED, so not listed
    (`composio_accounts.account_ids`) and never removed, and its row, stored after this read, is kept by its
    own sweep. The window left is the adoption window: between that connect's link and its upsert no row
    holds its account, and if the person finishes signing in right then (milliseconds) the account is
    ACTIVE while unheld, so this listing removes it, as a `start` in that window would have adopted it. That
    is benign: the racing connect's row is stored `pending` with an account Composio no longer has, `sync`
    finds it GONE and moves the row to `not_connected`, and the person connects again. Best effort, each
    outcome logged (account ids are identifiers, not secrets)."""
    with db.connect() as conn:
        _lock(conn, org_id, key)
        keep = _held_accounts(conn, org_id) | {started}
        conn.commit()  # releases the lock
    try:
        others = [a for a in composio_accounts.account_ids(user_id, toolkit) if a not in keep]
    except ApiProblem as problem:
        log.warning("Could not list the Composio accounts of %s for %s: %s", key, org_id, problem.code)
        return
    _remove_each(org_id, key, others)


def _remove_each(org_id: str, key: str, account_ids: list[str]) -> None:
    for account_id in account_ids:
        try:
            composio_accounts.remove(account_id)
        except ApiProblem as problem:
            log.warning(
                "Could not remove the Composio account %s of %s for %s: %s",
                account_id,
                key,
                org_id,
                problem.code,
            )
            continue
        log.info(
            "Removed the Composio account %s of %s for %s, left by an earlier failure",
            account_id,
            key,
            org_id,
        )


def _started(
    connectors: dict[str, dict], key: str, row: dict, org_id: str, redirect_url: str | None
) -> ConnectStarted:
    connection = _connection(connectors, key, row, org_id)
    return ConnectStarted.model_validate({**connection.model_dump(), "redirect_url": redirect_url})


def connect_live(org_id: str, user_id: str, name: str) -> ConnectStarted:
    """Start connecting the org's own account: a Composio sign-in link that returns to the web's Connections
    page. The row is pending, mode composio, with the new account id and no grants (its revoked grants are
    kept), until `sync` finds the account ACTIVE. A row whose account is already connected (it routes through
    Composio) is returned as it is: no new link, and its grants are kept. Any other account the row holds is
    removed at Composio first, so it is never adopted again silently; when that fails nothing changes (503).
    The row is stored only while it still holds the account read before the link was made, or none at all (a
    compare-and-set; a row holding nothing lost nothing, since only a removal clears the id): a connect racing
    this one stored its own account meanwhile, and that one wins, so the row ever holds one account. The
    loser's link is then removed at Composio (`_remove_and_forget`, best effort), unless both adopted the
    same account, which the winner now holds; the row as it is comes back, with no sign-in page: an unheld
    link would otherwise be an orphan if the person finished it. Once the new row is stored, the org's other
    accounts for the toolkit are swept away (`_sweep`)."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    app = app_name(connectors, key)
    toolkit = str((connectors.get(key) or {}).get("toolkit") or "")
    if not toolkit:
        raise ApiProblem(
            409,
            NO_LIVE_TOOLKIT,
            f"{app} cannot be connected to a real account yet. Use simulated data instead.",
        )
    with db.connect() as conn:
        _lock(conn, org_id, key)
        current = _rows(conn, org_id).get(key)
        conn.commit()
    if current is not None and routes.route_of(org_id, current).mode == "composio":
        return _started(connectors, key, current, org_id, None)
    held = (current or {}).get("account_id")
    if held:
        composio_accounts.remove(held)
    user = routes.org_user_id(org_id)
    started = composio_accounts.start(user, toolkit, _callback_url(key), app)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        stored = conn.execute(
            "INSERT INTO connections (org_id, app, status, mode, grants, connected_by, account_id) "
            "VALUES (%s, %s, 'pending', 'composio', '[]'::jsonb, %s, %s) ON CONFLICT (org_id, app) "
            "DO UPDATE SET status = 'pending', mode = 'composio', grants = '[]'::jsonb, "
            "connected_by = EXCLUDED.connected_by, account_id = EXCLUDED.account_id, connected_at = now() "
            "WHERE connections.account_id IS NOT DISTINCT FROM %s OR connections.account_id IS NULL",
            (org_id, key, user_id, started.account_id, held),
        ).rowcount
        row = _rows(conn, org_id)[key]
        conn.commit()
    if stored != 1:
        log.info("A connect of %s for %s raced another, which stored its account first", key, org_id)
        if row["account_id"] != started.account_id:  # else both adopted the same account: the winner holds it
            _remove_and_forget(org_id, key, started.account_id)
        return _started(connectors, key, row, org_id, None)
    _sweep(org_id, key, user, toolkit, started.account_id)
    return _started(connectors, key, row, org_id, started.redirect_url)


def _synced_status(current: str, account_status: str) -> str:
    """A Composio connection's status after its account reported `account_status`: connected when ACTIVE,
    unchanged while the sign-in is still in progress; otherwise a pending sign-in did not finish
    (not_connected) and a connected account needs signing in again (needs_reauth)."""
    if account_status == composio_accounts.ACTIVE:
        return "connected"
    if account_status in composio_accounts.WAITING:
        return current
    return "not_connected" if current == "pending" else "needs_reauth"


def sync(org_id: str, name: str) -> Connection:
    """Bring the org's connection to its own account up to date with Composio, after the person comes back
    from signing in. From pending to connected it gains a grant per capability for each added pack that uses
    the app (`grants_for`), as connecting to sandbox data does; a pending sign-in that failed leaves the row
    not connected with no grants, and its account is removed at Composio and forgotten (an account Composio
    no longer has is forgotten at once; when the removal fails the id stays for a later connect or disconnect
    to retry, and the row carries the `NOT_REMOVED` notice); otherwise its grants stay as they are, so a
    revoked grant is never restored. A sandbox row, one with no account, or a disconnected one is returned as
    it is, without asking Composio. The row is read and updated under the (org, app) lock, released while
    Composio answers, and the update matches the account, mode and status read, so a connect or switch in
    between is never overwritten."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        row = _rows(conn, org_id).get(key)
        conn.commit()  # releases the lock
    if row is None or row["mode"] != "composio" or not row["account_id"] or row["status"] == "not_connected":
        return _connection(connectors, key, row, org_id)
    was, account = str(row["status"]), str(row["account_id"])
    account_status = composio_accounts.status(account)
    status = _synced_status(was, account_status)
    granting = was == "pending" and status == "connected"
    gone = account_status == composio_accounts.GONE
    # The definitions `grants_for` needs, read before the connection below is taken (see `_read_packs`).
    read, contracts = _read_packs(org_id) if granting else (_Packs({}, {}), {})
    where = "WHERE org_id = %s AND app = %s AND account_id = %s AND mode = 'composio' AND status = %s"
    moved = False  # whether this sync's own update disconnected the row (another sync may have won)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        if granting:
            bodies, contracts = _fresh(conn, org_id, read, contracts)
            grants = grants_for(conn, connectors, bodies, contracts, org_id, key)
            conn.execute(
                f"UPDATE connections SET status = %s, grants = %s {where}",
                (status, Jsonb(grants), org_id, key, account, was),
            )
        elif status == "not_connected":
            forget = ", account_id = NULL" if gone else ""  # nothing to remove at Composio
            moved = (
                conn.execute(
                    f"UPDATE connections SET status = %s, grants = '[]'::jsonb{forget} {where}",
                    (status, org_id, key, account, was),
                ).rowcount
                == 1
            )
        elif status != was:
            conn.execute(f"UPDATE connections SET status = %s {where}", (status, org_id, key, account, was))
        row = _rows(conn, org_id).get(key)
        conn.commit()
    if moved and not gone:
        row = _remove_and_forget(org_id, key, account) or row
    return _connection(connectors, key, row, org_id)


def _remove_and_forget(org_id: str, key: str, account: str) -> dict | None:
    """Remove the account at Composio, outside any lock, then forget it on the org's row while the row still
    holds it, disconnected (a connect in between stored its own account, which stays): the row as it is
    then. None, logged, when Composio could not remove it: the id stays on the row for a later connect or
    disconnect to retry, and the row carries the `NOT_REMOVED` notice meanwhile."""
    try:
        composio_accounts.remove(account)
    except ApiProblem as problem:
        log.warning(
            "Could not remove the Composio account %s of %s for %s: %s", account, key, org_id, problem.code
        )
        return None
    with db.connect() as conn:
        _lock(conn, org_id, key)
        conn.execute(
            "UPDATE connections SET account_id = NULL "
            "WHERE org_id = %s AND app = %s AND account_id = %s AND status = 'not_connected'",
            (org_id, key, account),
        )
        row = _rows(conn, org_id).get(key)
        conn.commit()
    return row


def disconnect(org_id: str, name: str, role: str) -> Connection:
    """The org's app is no longer connected and holds no grants (idempotent). A row in mode composio (the
    org's own account, whatever its status) is only disconnected by `role` in `REAL_ACCOUNT_ROLES` (403
    otherwise, checked under the lock); a sandbox row by any member. Any Composio account the row still
    holds, whatever its mode (a switch to sandbox data whose retirement failed leaves one), is then removed
    at Composio: runs stop using it at once either way, since they read the row per call. When Composio could
    not remove it, the row keeps the account id (a later connect or disconnect tries again) and the answer
    carries a notice. The row is changed under the (org, app) lock, released while Composio answers, and the
    id is forgotten only while the row still holds it, disconnected: a connect in between stored its own
    account, which stays."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        current = _rows(conn, org_id).get(key)
        if current is not None and current["mode"] == "composio":
            require_real_account_role(role)
        conn.execute(
            "UPDATE connections SET status = 'not_connected', grants = '[]'::jsonb "
            "WHERE org_id = %s AND app = %s",
            (org_id, key),
        )
        row = _rows(conn, org_id).get(key)
        conn.commit()  # releases the lock
    # Carries the notice while the row holds an account; cleared below once Composio has removed it.
    connection = _connection(connectors, key, row, org_id)
    account = row["account_id"] if row is not None else None
    if not account or _remove_and_forget(org_id, key, account) is None:
        return connection
    return connection.model_copy(update={"notice": None})


def revoke_grant(org_id: str, name: str, install: str, capability: str) -> None:
    """Remove one grant from the org's connection and remember it as revoked, so recomputing the connection's
    grants does not bring it back; 404 when it holds no such grant. Under the (org, app) lock, so a connect
    or re-grant in flight never writes grants read before this revocation."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        row = conn.execute(
            "SELECT grants, revoked_grants FROM connections WHERE org_id = %s AND app = %s FOR UPDATE",
            (org_id, key),
        ).fetchone()
        grants = list(row["grants"] or []) if row else []
        kept = [g for g in grants if not (g.get("install") == install and g.get("capability") == capability)]
        if len(kept) == len(grants):
            raise ApiProblem(404, "NOT_FOUND", "No such grant.")
        revoked = list(row["revoked_grants"] or [])
        if (install, capability) not in _revoked_keys(revoked):
            revoked.append({"install": install, "capability": capability})
        conn.execute(
            "UPDATE connections SET grants = %s, revoked_grants = %s WHERE org_id = %s AND app = %s",
            (Jsonb(kept), Jsonb(revoked), org_id, key),
        )
        conn.commit()


def allow_grant(org_id: str, name: str, install: str, capability: str) -> Connection:
    """Allow a grant a person revoked again: the revocation is forgotten, and the grant comes back only when
    an added pack still uses the capability under its Work Contract (`grants_for`, which fails closed), on a
    row that keeps grants (`KEEPS_GRANTS`; a pending sign-in gains it when `sync` grants). 404 when the org's
    connection holds no such revocation: another org's connection looks the same as a missing one. The row is
    read under the (org, app) lock and locked itself (FOR UPDATE), so a revoke or a pack added meanwhile is
    never written over from a stale read."""
    connectors = latest_bodies("connector")
    key = _resolve(connectors, name)
    read, contracts = _read_packs(org_id)
    with db.connect() as conn:
        _lock(conn, org_id, key)
        bodies, contracts = _fresh(conn, org_id, read, contracts)
        row = conn.execute(
            "SELECT grants, revoked_grants, status FROM connections "
            "WHERE org_id = %s AND app = %s FOR UPDATE",
            (org_id, key),
        ).fetchone()
        revoked = list(row["revoked_grants"] or []) if row else []
        kept = [r for r in revoked if (install, capability) not in _revoked_keys([r])]
        if row is None or len(kept) == len(revoked):
            raise ApiProblem(404, "NOT_FOUND", "No such revoked grant.")
        conn.execute(
            "UPDATE connections SET revoked_grants = %s WHERE org_id = %s AND app = %s",
            (Jsonb(kept), org_id, key),
        )
        grants = list(row["grants"] or [])
        held = {(g.get("install"), g.get("capability")) for g in grants}
        back = [
            g
            for g in grants_for(conn, connectors, bodies, contracts, org_id, key)
            if (g["install"], g["capability"]) == (install, capability) and (install, capability) not in held
        ]
        if back and row["status"] in KEEPS_GRANTS:
            conn.execute(
                "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s",
                (Jsonb(grants + back), org_id, key),
            )
        row = _rows(conn, org_id)[key]
        conn.commit()
    return _connection(connectors, key, row, org_id)


def rename_install(conn, org_id: str, key: str, old: str, new: str) -> None:
    """A pack the org added was renamed: its grants on the org's connection to `key`, and the ones a person
    revoked, follow the new name (grants are keyed by pack name), so nothing is lost and nothing revoked comes
    back. Under the (org, app) lock and FOR UPDATE, like `revoke_grant`. Runs on the caller's connection and
    does not commit."""
    if old == new:
        return
    _lock(conn, org_id, key)
    row = conn.execute(
        "SELECT grants, revoked_grants FROM connections WHERE org_id = %s AND app = %s FOR UPDATE",
        (org_id, key),
    ).fetchone()
    if row is None:
        return

    def renamed(items: list[dict] | None) -> list[dict]:
        return [
            {**g, "install": new} if isinstance(g, dict) and g.get("install") == old else g
            for g in items or []
        ]

    conn.execute(
        "UPDATE connections SET grants = %s, revoked_grants = %s WHERE org_id = %s AND app = %s",
        (Jsonb(renamed(row["grants"])), Jsonb(renamed(row["revoked_grants"])), org_id, key),
    )


def regrant(conn, connectors: dict[str, dict], org_id: str, keys: set[str]) -> None:
    """Recompute the grants of the org's connections to `keys` that keep grants (`KEEPS_GRANTS`) from its
    added packs as they are pinned now, read on `conn` (so an installation moved in this transaction counts):
    a grant the pinned versions no longer use goes, a new one comes, a revoked one stays revoked. Each app's
    (org, app) lock before its row, in key order. Runs on the caller's connection and does not commit."""
    packs, contracts = _definitions(conn, org_id)
    for key in sorted(keys):
        _lock(conn, org_id, key)
        row = conn.execute(
            "SELECT status FROM connections WHERE org_id = %s AND app = %s FOR UPDATE", (org_id, key)
        ).fetchone()
        if row is None or row["status"] not in KEEPS_GRANTS:
            continue
        grants = grants_for(conn, connectors, packs.bodies, contracts, org_id, key)
        conn.execute(
            "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s", (Jsonb(grants), org_id, key)
        )


def grant_pack(
    conn, connectors: dict[str, dict], org_id: str, pack: dict, contracts: dict[str, dict]
) -> None:
    """A pack was added: the org's apps it uses whose rows keep grants (`KEEPS_GRANTS`: connected, sandbox,
    or needing sign-in again) gain its grants (those it holds already are left as they are, and those a
    person revoked stay revoked). Runs on the caller's connection and does not commit. Each app's (org, app)
    lock is taken before its row, so a connect or re-grant of the app in flight (which computes grants from
    the installations it read under that lock) lands wholly before or after this, never over it. Lock order:
    registry, installations, (org, app), row."""
    name = str(pack.get("name") or pack.get("slug"))
    capabilities = contract_capabilities(pack, contracts)
    # In key order, as every pack's grants are: two packs granted at once never wait on each other's rows.
    for key in sorted({str(c) for c in pack.get("connectors") or []}):
        _lock(conn, org_id, key)
        row = conn.execute(
            "SELECT grants, status, revoked_grants FROM connections "
            "WHERE org_id = %s AND app = %s FOR UPDATE",
            (org_id, key),
        ).fetchone()
        if row is None or row["status"] not in KEEPS_GRANTS:
            continue
        grants = list(row["grants"] or [])
        held = {(g.get("install"), g.get("capability")) for g in grants}
        skip = held | _revoked_keys(row["revoked_grants"])
        added = [
            g
            for g in pack_grants(connectors.get(key) or {}, name, capabilities)
            if (name, g["capability"]) not in skip
        ]
        if added:
            conn.execute(
                "UPDATE connections SET grants = %s WHERE org_id = %s AND app = %s",
                (Jsonb(grants + added), org_id, key),
            )


def missing_apps(org_id: str, connector_keys: list[str]) -> list[str]:
    """Display names of `connector_keys` the org has no usable connection to: the same rule its runs follow
    (`routes.route_of`), so the start gate and the worker agree."""
    connectors = latest_bodies("connector")
    by_app = routes.org_routes(org_id)
    return [app_name(connectors, k) for k in connector_keys if by_app.get(k, routes.NONE).mode == "none"]
