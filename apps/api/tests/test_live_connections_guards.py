"""Guards on the org's own app accounts through Composio: a listed account is checked against the filter
before it is adopted or removed (one Composio project holds every org's accounts), and two connects at once
leave the row holding one account. Fake Composio client, no network."""

import pytest

from app import composio_accounts, live_connections
from app.errors import ApiProblem
from tests.fake_composio import LINK_URL, composio  # noqa: F401  (composio is a fixture)
from tests.test_live_catalog import (  # noqa: F401  (live, starts, ana are fixtures)
    PACK_NAME,
    _rows,
    ana,
    live,
    starts,
)

BACK = "https://app.example.com/app/connections?connected=stripe"
GRANT = {"app": "stripe", "install": PACK_NAME, "capability": "payments.read"}
FORBIDDEN_DETAIL = "Only an owner or admin can change the org's real accounts."


# --- the sweep's listing: only the user's token-holding accounts for the toolkit --------------------------


def test_account_ids_leaves_out_another_users_account_the_listing_answered(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_theirs"]
    composio.connected_accounts.owners["ca_theirs"] = "org:o2"
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]


def test_account_ids_leaves_out_another_toolkits_account_the_listing_answered(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_mail"]
    composio.connected_accounts.toolkits["ca_mail"] = "gmail"
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]


def test_account_ids_leaves_out_an_account_whose_status_was_not_asked_for(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_half"]
    composio.connected_accounts.statuses["ca_half"] = "INITIATED"
    composio.connected_accounts.unfiltered = True  # the server ignored `statuses`
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]


def test_account_ids_leaves_out_an_account_without_the_expected_fields(composio, monkeypatch):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_bare"]
    real_item = composio.connected_accounts._item

    def item(nanoid, query):
        full = real_item(nanoid, query)
        if nanoid == "ca_bare":
            del full.toolkit
        return full

    monkeypatch.setattr(composio.connected_accounts, "_item", item)
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]


def test_a_live_connect_never_removes_another_users_account(ana, composio, db):  # noqa: F811
    composio.connected_accounts.held = ["ca_theirs"]
    composio.connected_accounts.owners["ca_theirs"] = "org:someone-else"
    res = ana.post("/v1/connections/stripe:connect", json={"mode": "live"})
    assert res.status_code == 200, res.text
    assert composio.connected_accounts.deleted == []
    assert composio.connected_accounts.held == ["ca_theirs", "ca_new"]


# --- adoption: only the user's own ACTIVE account ------------------------------------------------------


def _start():
    return composio_accounts.start("org:o1", "stripe", BACK, "Stripe")


def test_start_never_adopts_another_users_active_account(composio):  # noqa: F811
    composio.connected_accounts.active = ["ca_theirs"]
    composio.connected_accounts.owners["ca_theirs"] = "org:o2"
    with pytest.raises(ApiProblem) as err:
        _start()
    assert (err.value.status, err.value.code) == (503, composio_accounts.SERVICE_DOWN)
    assert composio.connected_accounts.linked == []


def test_start_never_adopts_an_account_that_is_not_active(composio):  # noqa: F811
    composio.connected_accounts.active = ["ca_old"]
    composio.connected_accounts.statuses["ca_old"] = "EXPIRED"
    composio.connected_accounts.unfiltered = True  # the server ignored `statuses`
    with pytest.raises(ApiProblem) as err:
        _start()
    assert (err.value.status, err.value.code) == (503, composio_accounts.SERVICE_DOWN)


def test_start_still_adopts_the_users_own_active_account(composio):  # noqa: F811
    composio.connected_accounts.active = ["ca_mine"]
    assert _start() == composio_accounts.Started("ca_mine", BACK)


# --- two connects at once --------------------------------------------------------------------------------


def _tab_b_connects_while_tab_a_links(monkeypatch, org_id: str) -> list:
    """Tab B's whole live connect of Stripe runs inside tab A's `composio_accounts.start`, once: after A read
    the row and before A's own link is made. Returns the list B's answer lands in."""
    real_start, inner, racing = composio_accounts.start, [], []

    def start(user_id, toolkit, callback_url, app):
        if not racing:
            racing.append(True)
            inner.append(live_connections.connect_live(org_id, "uid_ben", "stripe"))  # tab B
        return real_start(user_id, toolkit, callback_url, app)

    monkeypatch.setattr(composio_accounts, "start", start)
    return inner


def test_two_connects_at_once_leave_one_account_and_forget_the_losers_link(ana, composio, db, monkeypatch):  # noqa: F811
    """B stores ca_1; A's link is ca_2. A's store misses (the row no longer holds what A read: nothing), so
    A removes ca_2 at Composio and answers with the row as it is, pending on ca_1, with no sign-in page."""
    composio.connected_accounts.next_ids = ["ca_1", "ca_2"]
    inner = _tab_b_connects_while_tab_a_links(monkeypatch, ana.org_id)
    res = ana.post("/v1/connections/stripe:connect", json={"mode": "live"})  # tab A
    assert res.status_code == 200, res.text
    [b] = inner
    assert b.redirect_url == LINK_URL and b.status == "pending"
    assert res.json()["status"] == "pending" and res.json().get("redirectUrl") is None
    assert composio.connected_accounts.linked and len(composio.connected_accounts.linked) == 2
    rows = _rows(db, "SELECT account_id, connected_by FROM connections WHERE org_id = %s", ana.org_id)
    assert rows == [{"account_id": "ca_1", "connected_by": "uid_ben"}]
    assert composio.connected_accounts.deleted == [("ca_2", True)]
    assert composio.connected_accounts.held == ["ca_1"]


def test_a_losing_connect_whose_link_cannot_be_removed_still_answers_the_row(ana, composio, db, monkeypatch):  # noqa: F811
    composio.connected_accounts.next_ids = ["ca_1", "ca_2"]
    _tab_b_connects_while_tab_a_links(monkeypatch, ana.org_id)
    real_remove = composio_accounts.remove

    def remove(account_id):
        if account_id == "ca_2":
            raise ApiProblem(503, composio_accounts.SERVICE_DOWN, "down")
        real_remove(account_id)

    monkeypatch.setattr(composio_accounts, "remove", remove)
    res = ana.post("/v1/connections/stripe:connect", json={"mode": "live"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending" and res.json().get("redirectUrl") is None
    [row] = _rows(db, "SELECT account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"account_id": "ca_1"}


def test_two_connects_that_adopt_the_same_account_keep_it(ana, composio, db, monkeypatch):  # noqa: F811
    """Both tabs find the org's ACTIVE account unheld and adopt it (`composio_accounts.start`): B stores it,
    A's store misses, and A must not remove the account B now holds."""
    composio.connected_accounts.active = ["ca_x"]
    inner = _tab_b_connects_while_tab_a_links(monkeypatch, ana.org_id)
    res = ana.post("/v1/connections/stripe:connect", json={"mode": "live"})
    assert res.status_code == 200, res.text
    assert len(inner) == 1 and composio.connected_accounts.linked == []
    assert res.json()["status"] == "pending" and res.json().get("redirectUrl") is None
    assert composio.connected_accounts.deleted == []
    [row] = _rows(db, "SELECT account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"account_id": "ca_x"}


def test_a_connect_still_stores_its_link_when_the_row_was_emptied_meanwhile(ana, composio, db, monkeypatch):  # noqa: F811
    """A sync or disconnect cleared the row's account between the read and the link (the account this
    connect had just removed): the row holds nothing, so the fresh link is stored and the sign-in page
    answered, rather than removed with a false "finish signing in"."""
    _row(db, ana.org_id, "stripe", "needs_reauth", "composio", "ca_old")
    composio.connected_accounts.held = ["ca_old"]
    real_start = composio_accounts.start

    def start(user_id, toolkit, callback_url, app):
        db.execute(
            "UPDATE connections SET account_id = NULL, status = 'not_connected' WHERE org_id = %s",
            (ana.org_id,),
        )
        db.commit()
        return real_start(user_id, toolkit, callback_url, app)

    monkeypatch.setattr(composio_accounts, "start", start)
    res = ana.post("/v1/connections/stripe:connect", json={"mode": "live"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending" and res.json()["redirectUrl"] == LINK_URL
    assert composio.connected_accounts.deleted == [("ca_old", True)]
    [row] = _rows(db, "SELECT status, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"status": "pending", "account_id": "ca_new"}


# --- only an owner or admin binds, replaces or removes the org's real accounts ----------------------------


def _row(db, org_id: str, app: str, status: str, mode: str, account: str | None = None) -> None:
    db.execute(
        "INSERT INTO connections (org_id, app, status, mode, grants, connected_by, account_id) "
        "VALUES (%s, %s, %s, %s, '[]'::jsonb, 'uid_ana', %s)",
        (org_id, app, status, mode, account),
    )
    db.commit()


def _as_role(db, user, role: str) -> None:
    """Ana's role in her org from now on (read per request, so the earlier setup ran as the owner)."""
    db.execute(
        "UPDATE org_members SET role = %s WHERE org_id = %s AND user_id = 'uid_ana'", (role, user.org_id)
    )
    db.commit()


def _real_row(user, fake, db) -> None:
    _row(db, user.org_id, "stripe", "connected", "composio", "ca_1")
    fake.connected_accounts.held = ["ca_1"]


def _granted(user, fake, db) -> None:
    assert user.hire().status_code == 201
    assert user.connect("stripe").json()["grants"] != []


def _revoked(user, fake, db) -> None:
    _granted(user, fake, db)
    assert user.delete("/v1/grants", params=GRANT).status_code == 204


# Each gated action: how the owner sets the org up for it, the call, and the status it answers when allowed.
GATED = {
    "connect_live": (
        lambda u, c, d: None,
        lambda u: u.post("/v1/connections/stripe:connect", json={"mode": "live"}),
        200,
    ),
    "disconnect_real": (_real_row, lambda u: u.post("/v1/connections/stripe:disconnect"), 200),
    "connect_sandbox_over_real": (_real_row, lambda u: u.connect("stripe"), 200),
    "revoke": (_granted, lambda u: u.delete("/v1/grants", params=GRANT), 204),
    "allow_again": (_revoked, lambda u: u.post("/v1/grants", params=GRANT), 200),
}


def _state(db, fake, org_id: str) -> tuple:
    rows = _rows(
        db,
        "SELECT app, status, mode, grants, account_id, revoked_grants FROM connections WHERE org_id = %s "
        "ORDER BY app",
        org_id,
    )
    return rows, list(fake.connected_accounts.linked), list(fake.connected_accounts.deleted)


@pytest.mark.parametrize("action", sorted(GATED))
@pytest.mark.parametrize("role", ["member", "reviewer"])
def test_a_member_or_reviewer_cannot_change_the_orgs_real_accounts(ana, composio, db, role, action):  # noqa: F811
    setup, call, _ = GATED[action]
    setup(ana, composio, db)
    _as_role(db, ana, role)
    before = _state(db, composio, ana.org_id)
    res = call(ana)
    assert res.status_code == 403, res.text
    assert (res.json()["code"], res.json()["detail"]) == ("FORBIDDEN", FORBIDDEN_DETAIL)
    assert _state(db, composio, ana.org_id) == before


@pytest.mark.parametrize("action", sorted(GATED))
def test_an_admin_changes_the_orgs_real_accounts(ana, composio, db, action):  # noqa: F811
    setup, call, status = GATED[action]
    setup(ana, composio, db)
    _as_role(db, ana, "admin")
    res = call(ana)
    assert res.status_code == status, res.text


def test_a_member_still_connects_simulated_data_syncs_and_disconnects_a_simulated_app(ana, composio, db):  # noqa: F811
    assert ana.hire().status_code == 201
    _as_role(db, ana, "member")
    assert ana.connect("stripe").json()["status"] == "sandbox"
    assert ana.post("/v1/connections/stripe:sync").status_code == 200
    assert ana.post("/v1/connections/stripe:disconnect").json()["status"] == "not_connected"


def test_a_member_syncs_a_sign_in_an_admin_started(ana, composio, db):  # noqa: F811
    _row(db, ana.org_id, "stripe", "pending", "composio", "ca_1")
    composio.connected_accounts.held = ["ca_1"]
    _as_role(db, ana, "member")
    assert ana.post("/v1/connections/stripe:sync").json()["status"] == "connected"


def test_a_member_connects_simulated_data_over_a_not_connected_row_with_a_leftover_account(ana, composio, db):  # noqa: F811
    """Retiring the leftover account is cleanup, not replacing a real account."""
    _row(db, ana.org_id, "stripe", "not_connected", "composio", "ca_left")
    composio.connected_accounts.held = ["ca_left"]
    _as_role(db, ana, "member")
    assert ana.connect("stripe").json()["status"] == "sandbox"
    assert composio.connected_accounts.deleted == [("ca_left", True)]
    [row] = _rows(db, "SELECT mode, account_id FROM connections WHERE org_id = %s", ana.org_id)
    assert row == {"mode": "sandbox", "account_id": None}
