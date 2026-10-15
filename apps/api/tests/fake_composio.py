"""A stand-in for the Composio SDK client that `app.composio_accounts` builds: it records every call, answers
from its fields and never reaches the network. Use the `composio` fixture."""

from types import SimpleNamespace

import pytest
from composio.exceptions import ComposioMultipleConnectedAccountsError

from app import composio_accounts

LINK_URL = "https://connect.example/link/abc"


class NotFound(Exception):
    status_code = 404


class FakeAuthConfigs:
    def __init__(self) -> None:
        self.items: list[SimpleNamespace] = []
        self.queries: list[dict] = []
        self.created: list[tuple[str, dict]] = []
        self.fail_list: Exception | None = None
        self.fail_create: Exception | None = None

    def list(self, **query):
        self.queries.append(query)
        if self.fail_list is not None:
            raise self.fail_list
        return SimpleNamespace(items=list(self.items))

    def create(self, toolkit: str, options: dict):
        if self.fail_create is not None:
            raise self.fail_create
        self.created.append((toolkit, options))
        return SimpleNamespace(id="ac_new")


class FakeAccounts:
    def __init__(self) -> None:
        self.linked: list[tuple[str, str, str | None]] = []
        self.redirect_url: str | None = LINK_URL  # what `link` answers with
        self.active: list[str] = []  # ids of ACTIVE accounts the user already has
        self.held: list[str] = []  # ids of every account the user has for the toolkit (any status)
        self.page_size: int | None = None  # when set, `list` answers `held` in pages with a cursor
        self.cursor_mode: str | None = None  # "loop": the same next cursor forever; "endless": a new one each
        self.queries: list[dict] = []
        self.statuses: dict[str, str] = {}  # an account's status; ACTIVE when not set (`_status`)
        self.owners: dict[str, str] = {}  # an account's Composio user; the query's user when not set
        self.toolkits: dict[str, str] = {}  # an account's toolkit slug; the query's toolkit when not set
        self.unfiltered = False  # when set, `list` ignores the query's `statuses` (a server-side filter miss)
        self.next_ids: list[str] = []  # ids the next links answer with, in order, before `ca_new`
        self.got: list[str] = []
        self.deleted: list[tuple[str, bool | None]] = []
        self.fail_link: Exception | None = None
        self.fail_list: Exception | None = None
        self.fail_get: Exception | None = None
        self.fail_delete: Exception | None = None

    def link(
        self,
        user_id,
        auth_config_id,
        *,
        callback_url=None,
        alias=None,
        allow_multiple=False,
        experimental=None,
    ):
        if self.fail_link is not None:
            raise self.fail_link
        if self.active and not allow_multiple:
            raise ComposioMultipleConnectedAccountsError("an ACTIVE account exists")
        self.linked.append((user_id, auth_config_id, callback_url))
        nanoid = self.next_ids.pop(0) if self.next_ids else "ca_new"
        self.held.append(nanoid)
        self.statuses[nanoid] = "INITIATED"  # a new link: the person has not signed in yet
        return SimpleNamespace(id=nanoid, status="INITIATED", redirect_url=self.redirect_url)

    def _status(self, nanoid: str) -> str | None:
        """The account's status as `get` and `list` both see it: `statuses`, else ACTIVE for an account the
        user has (`held`, `active`); None when the fake knows no such account."""
        if nanoid in self.statuses:
            return self.statuses[nanoid]
        return "ACTIVE" if nanoid in self.held or nanoid in self.active else None

    def forget(self, nanoid: str) -> None:
        """The account is gone at Composio (deleted there, outside the API): `get` answers 404 from now on."""
        self.statuses.pop(nanoid, None)
        self.held = [i for i in self.held if i != nanoid]
        self.active = [i for i in self.active if i != nanoid]

    def _item(self, nanoid: str, query: dict) -> SimpleNamespace:
        """A listed account as the SDK answers it: its id, user, toolkit and status. The user and toolkit are
        the query's unless `owners` / `toolkits` say otherwise (an account the server's filter missed)."""
        user = self.owners.get(nanoid) or (query.get("user_ids") or [""])[0]
        toolkit = self.toolkits.get(nanoid) or (query.get("toolkit_slugs") or [""])[0]
        return SimpleNamespace(
            id=nanoid, user_id=user, toolkit=SimpleNamespace(slug=toolkit), status=self._status(nanoid)
        )

    def list(self, **query):
        """The user's accounts (`held` and `active`), only those whose status (`_status`) the query's
        `statuses` names (every one when `unfiltered`), one page at a time when `page_size` is set (the
        cursor is the next index, as text). `cursor_mode` makes the paging misbehave for the guard tests."""
        self.queries.append(query)
        if self.fail_list is not None:
            raise self.fail_list
        wanted = None if self.unfiltered else query.get("statuses")
        ids = [
            i for i in dict.fromkeys(self.held + self.active) if wanted is None or self._status(i) in wanted
        ]
        start = int(query.get("cursor") or 0) if self.cursor_mode is None else 0
        end = len(ids) if self.page_size is None else min(start + self.page_size, len(ids))
        next_cursor = str(end) if end < len(ids) else None
        if self.cursor_mode == "loop":
            next_cursor = "again"
        elif self.cursor_mode == "endless":
            next_cursor = f"page-{len(self.queries)}"
        return SimpleNamespace(items=[self._item(i, query) for i in ids[start:end]], next_cursor=next_cursor)

    def get(self, nanoid):
        self.got.append(nanoid)
        if self.fail_get is not None:
            raise self.fail_get
        status = self._status(nanoid)
        if status is None:
            raise NotFound(nanoid)
        return SimpleNamespace(id=nanoid, status=status)

    def delete(self, nanoid, *, revoke_on_delete=None):
        if self.fail_delete is not None:
            raise self.fail_delete
        self.deleted.append((nanoid, revoke_on_delete))
        self.active = [i for i in self.active if i != nanoid]
        self.held = [i for i in self.held if i != nanoid]
        return SimpleNamespace(success=True)


class FakeComposio:
    def __init__(self) -> None:
        self.auth_configs = FakeAuthConfigs()
        self.connected_accounts = FakeAccounts()


@pytest.fixture
def composio(monkeypatch) -> FakeComposio:
    fake = FakeComposio()
    monkeypatch.setenv("COMPOSIO_API_KEY", "test-key")
    monkeypatch.setattr(composio_accounts, "_client", lambda: fake)
    return fake
