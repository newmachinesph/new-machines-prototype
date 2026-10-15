"""How a live-workspace run reaches each app: the org's own connection row decides, per app and at the time
of each call. A Composio connection that is connected reaches the org's own account; a sandbox connection
serves sandbox data; anything else (not connected, pending, needs sign-in again, no row) runs nothing. Runs
without the `routing` mark (the demo workspace) keep NM_CONNECTOR_MODE (see `gateway.driver_of`).

A run pins each app's route mode and Composio account when it starts (`snapshot["routes"]` and
`snapshot["accounts"]`, see `pinned_routes`): a call whose app now has another usable route fails
(RouteChanged) instead of swapping sandbox for real data, or one account for another, mid-run."""

from dataclasses import dataclass, field
from typing import Literal

from app import db

ORG_ROUTING = "org"  # snapshot["routing"] of a run started in the live workspace

RouteMode = Literal["composio", "sandbox", "none"]


@dataclass(frozen=True)
class Route:
    mode: RouteMode
    user_id: str | None = None  # the Composio user (composio routes only)
    account_id: str | None = None  # the Composio connected account (composio routes only)
    # (install, capability) pairs the connection grants; not part of a route's identity
    grants: frozenset[tuple[str, str]] = field(default=frozenset(), compare=False, repr=False)

    def allows(self, install: str, capability: str) -> bool:
        """Whether the connection grants the hired pack `install` the tool capability `capability`."""
        return (install, capability) in self.grants


NONE = Route("none")


def org_user_id(org_id: str) -> str:
    """The Composio user id that owns an org's connected accounts: one per org, never a person's uid."""
    return f"org:{org_id}"


def _grants(row: dict) -> frozenset[tuple[str, str]]:
    return frozenset(
        (str(g.get("install")), str(g.get("capability")))
        for g in row.get("grants") or []
        if isinstance(g, dict)
    )


def route_of(org_id: str, row: dict | None) -> Route:
    """The route a `connections` row gives (`row` has status, mode, account_id and optionally grants). A
    connected Composio row without its account id reaches nothing: Composio would otherwise pick any ACTIVE
    account of the org's user."""
    if row is None:
        return NONE
    if row["mode"] == "composio" and row["status"] == "connected" and row.get("account_id"):
        return Route("composio", org_user_id(org_id), row.get("account_id"), _grants(row))
    if row["mode"] == "sandbox" and row["status"] == "sandbox":
        return Route("sandbox", grants=_grants(row))
    return NONE


# `route_of`'s rule as a SQL predicate on a `connections` row (`{c}` is the table alias), for counting the
# rows a run could reach: those `live_connections.shown_status` shows as connected or sandbox.
ROUTABLE_SQL = (
    "(({c}.mode = 'composio' AND {c}.status = 'connected' AND COALESCE({c}.account_id, '') <> '') "
    "OR ({c}.mode = 'sandbox' AND {c}.status = 'sandbox'))"
)

_SELECT = "SELECT app, status, mode, account_id, grants FROM connections WHERE org_id = %s"


def org_routes(org_id: str, conn=None) -> dict[str, Route]:
    """The org's route for every app it has a connection row for, by connector key. Runs on `conn` when
    given (without committing), else on its own connection."""
    if conn is not None:
        rows = conn.execute(_SELECT, (org_id,)).fetchall()
    else:
        with db.connect() as own:
            rows = own.execute(_SELECT, (org_id,)).fetchall()
    return {r["app"]: route_of(org_id, r) for r in rows}


def current_route(org_id: str | None, connector_key: str) -> Route:
    """The org's route for one app now. A run without an org has no route."""
    if not org_id:
        return NONE
    with db.connect() as conn:
        row = conn.execute(_SELECT + " AND app = %s", (org_id, connector_key)).fetchone()
    return route_of(org_id, row)


def pinned_routes(conn, org_id: str, connector_keys: list[str]) -> dict[str, dict[str, str]]:
    """The snapshot fields that pin each connector's route now for a live run: `routes` (connector key ->
    route mode) and `accounts` (connector key -> Composio connected account, composio routes only)."""
    org = org_routes(org_id, conn)
    found = {key: org.get(key, NONE) for key in connector_keys}
    return {
        "routes": {key: route.mode for key, route in found.items()},
        "accounts": {key: route.account_id for key, route in found.items() if route.account_id},
    }


def route_changed(snapshot: dict, connector_key: str, route: Route) -> bool:
    """Whether the app's route differs from the one pinned when the run started: another mode, or another
    Composio account. What a snapshot does not pin (no mode, or no account: runs pinned before accounts
    were) is not compared."""
    pinned = (snapshot.get("routes") or {}).get(connector_key)
    if pinned is not None and pinned != route.mode:
        return True
    account = (snapshot.get("accounts") or {}).get(connector_key)
    return account is not None and account != route.account_id
