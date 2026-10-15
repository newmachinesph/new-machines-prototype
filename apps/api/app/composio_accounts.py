"""The org's own app accounts through Composio: start a sign-in link, read an account's status, remove it.
Callers pass the org's Composio user (`routes.org_user_id`), never the demo user. The SDK client is built per
call from COMPOSIO_API_KEY; tests replace `_client`. SDK messages can carry request URLs, so problems say only
what failed, and logs carry the exception type."""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app import settings
from app.errors import ApiProblem

log = logging.getLogger(__name__)

ACTIVE = "ACTIVE"
WAITING = frozenset({"INITIALIZING", "INITIATED"})
GONE = "GONE"  # Composio has no such account (deleted there)
# Account statuses that can hold tokens, so are worth removing; not INITIATED / INITIALIZING (`account_ids`).
TOKEN_HOLDING = ("ACTIVE", "EXPIRED", "INACTIVE", "FAILED", "REVOKED")
PAGE_SIZE = 50  # accounts per `list` page
MAX_PAGES = 50  # pages `account_ids` follows before giving up on a listing that does not end
UNAVAILABLE = "LIVE_CONNECT_UNAVAILABLE"
SERVICE_DOWN = "CONNECTION_SERVICE_UNAVAILABLE"
MANAGED_AUTH = MappingProxyType({"type": "use_composio_managed_auth"})  # copied with dict() per call


@dataclass(frozen=True)
class Started:
    """A started sign-in: the Composio account id to store and the URL to send the browser to."""

    account_id: str
    redirect_url: str


def available() -> bool:
    """Whether real accounts can be connected here, that is, whether a Composio key is configured."""
    return settings.composio_api_key() is not None


def _client() -> Any:
    from composio import Composio

    # No SDK telemetry: it would send call names and, on errors, messages and tracebacks to a third party.
    return Composio(api_key=settings.composio_api_key(), allow_tracking=False)


def _connected_client() -> Any:
    if not available():
        raise ApiProblem(
            409,
            UNAVAILABLE,
            "Real accounts cannot be connected in this workspace yet. Use simulated data instead.",
        )
    return _client()


def _down(what: str, exc: Exception, detail: str) -> ApiProblem:
    log.warning("composio %s failed: %s", what, type(exc).__name__)
    return ApiProblem(503, SERVICE_DOWN, detail)


def _not_found(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 404


def _auth_config_id(client: Any, toolkit: str) -> str:
    """The newest enabled auth config of the toolkit, or a new Composio-managed one (what
    `toolkits.authorize` would create; `authorize` itself cannot take a callback URL)."""
    enabled = [a for a in client.auth_configs.list(toolkit_slug=toolkit).items if a.status == "ENABLED"]
    if enabled:
        return max(enabled, key=lambda a: a.created_at or "").id
    return client.auth_configs.create(toolkit, dict(MANAGED_AUTH)).id


def _outside_filter(item: Any, user_id: str, toolkit: str | None, statuses: tuple[str, ...]) -> str | None:
    """The name of the first field by which a listed account falls outside the filter the listing asked for
    (`user_id`, `toolkit`, `status`), or "fields" when the item lacks one; None when it is inside. One
    Composio project holds every org's accounts, so the server-side filter is checked again before an
    account is adopted or removed: a filter miss must never become another tenant's account. Logs name the
    field only, never the account."""
    try:
        if item.user_id != user_id:
            return "user_id"
        if toolkit is not None and item.toolkit.slug != toolkit:
            return "toolkit"
        if item.status not in statuses:
            return "status"
    except AttributeError as exc:
        log.warning("composio list answered an account without the expected fields: %s", type(exc).__name__)
        return "fields"
    return None


def _active_account_id(client: Any, user_id: str, auth_config_id: str) -> str | None:
    """The user's ACTIVE account on the auth config: the same filter `link` applies before it refuses to make
    a second one. None when Composio lists nothing after all, or lists an account that is not the user's
    ACTIVE one (`_outside_filter`): adopting it could bind another org's account."""
    found = client.connected_accounts.list(
        user_ids=[user_id], auth_config_ids=[auth_config_id], statuses=[ACTIVE], limit=1
    ).items
    if not found:
        return None
    field = _outside_filter(found[0], user_id, None, (ACTIVE,))
    if field is not None:
        log.warning(
            "composio list for the active account answered one outside the filter (%s); not adopted", field
        )
        return None
    return str(found[0].id)


def start(user_id: str, toolkit: str, callback_url: str, app: str) -> Started:
    """A Composio Connect Link for `user_id` to sign in to `toolkit`, returning to `callback_url`. When the
    user already has an ACTIVE account for it (an earlier sign-in finished but its row was lost), that account
    is adopted and the redirect goes straight back to `callback_url`, where the web finishes as usual."""
    from composio.exceptions import ComposioMultipleConnectedAccountsError

    client = _connected_client()
    detail = f"{app} could not be connected right now. Try again in a minute."
    try:
        auth_config_id = _auth_config_id(client, toolkit)
        try:
            request = client.connected_accounts.link(user_id, auth_config_id, callback_url=callback_url)
        except ComposioMultipleConnectedAccountsError:
            adopted = _active_account_id(client, user_id, auth_config_id)
            if adopted is None:
                log.warning("composio link for %s: an ACTIVE account was reported but is not listed", toolkit)
                raise ApiProblem(503, SERVICE_DOWN, detail) from None
            return Started(adopted, callback_url)
    except ApiProblem:
        raise
    except Exception as exc:
        raise _down(f"link for {toolkit}", exc, detail) from None
    if not request.redirect_url:
        raise ApiProblem(503, SERVICE_DOWN, detail)
    return Started(request.id, request.redirect_url)


def status(account_id: str) -> str:
    """The account's Composio status (ACTIVE, INITIATED, FAILED, EXPIRED, INACTIVE, REVOKED, ...), or GONE
    when Composio has no such account."""
    client = _connected_client()
    try:
        return str(client.connected_accounts.get(account_id).status)
    except Exception as exc:
        if _not_found(exc):
            return GONE
        raise _down("status", exc, "The connection service did not answer. Try again in a minute.") from None


def account_ids(user_id: str, toolkit: str) -> list[str]:
    """Ids of the accounts `user_id` has for `toolkit` at Composio that can hold tokens (`TOKEN_HOLDING`):
    what a sweep for accounts an earlier removal left behind looks at. A sign-in still in progress
    (INITIATED, INITIALIZING) is left out: it holds no tokens, Composio expires it, and it may be another
    connect's link whose row is not stored yet. An account the listing answers outside that filter (another
    user's, another toolkit's, a status not asked for) is logged and left out (`_outside_filter`): the caller
    removes what this returns, irreversibly. Follows the cursor through every page, and stops (logging) when
    a cursor repeats or after `MAX_PAGES`."""
    client = _connected_client()
    ids: dict[str, None] = {}
    query: dict[str, Any] = {
        "user_ids": [user_id],
        "toolkit_slugs": [toolkit],
        "statuses": list(TOKEN_HOLDING),
        "limit": PAGE_SIZE,
    }
    seen: set[str] = set()
    try:
        for _ in range(MAX_PAGES):
            page = client.connected_accounts.list(**query)
            for item in page.items:
                field = _outside_filter(item, user_id, toolkit, TOKEN_HOLDING)
                if field is None:
                    ids[str(item.id)] = None
                else:
                    log.warning(
                        "composio list for %s answered an account outside the filter (%s); skipped",
                        toolkit,
                        field,
                    )
            cursor = getattr(page, "next_cursor", None)
            if not cursor:
                return list(ids)
            if cursor in seen:
                log.warning("composio list for %s repeated cursor %s; stopping", toolkit, cursor)
                return list(ids)
            seen.add(cursor)
            query = {**query, "cursor": cursor}
    except Exception as exc:
        raise _down("list", exc, "The connection service did not answer. Try again in a minute.") from None
    log.warning("composio list for %s did not end after %d pages; stopping", toolkit, MAX_PAGES)
    return list(ids)


def remove(account_id: str) -> None:
    """Delete the account at Composio and revoke its tokens there. An account Composio no longer has counts as
    removed; any other failure raises (503), for the caller to surface."""
    client = _connected_client()
    try:
        client.connected_accounts.delete(account_id, revoke_on_delete=True)
    except Exception as exc:
        if _not_found(exc):
            return
        raise _down("delete", exc, "The connection service did not answer. Try again in a minute.") from None
