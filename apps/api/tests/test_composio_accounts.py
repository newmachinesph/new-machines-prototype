"""The org's own app accounts through Composio, with a fake client (no network)."""

from types import SimpleNamespace

import pytest
from composio.exceptions import ComposioMultipleConnectedAccountsError

from app import composio_accounts
from app.errors import ApiProblem
from tests.fake_composio import LINK_URL, NotFound, composio  # noqa: F401  (composio is a fixture)

BACK = "https://app.example.com/app/connections?connected=stripe"
STRIPE_DOWN = "Stripe could not be connected right now. Try again in a minute."
LISTING = {
    "user_ids": ["org:o1"],
    "toolkit_slugs": ["stripe"],
    "statuses": ["ACTIVE", "EXPIRED", "INACTIVE", "FAILED", "REVOKED"],
}
CALLS = {
    "start": lambda: composio_accounts.start("org:o1", "stripe", BACK, "Stripe"),
    "status": lambda: composio_accounts.status("ca_1"),
    "remove": lambda: composio_accounts.remove("ca_1"),
}


def test_start_links_the_org_user_with_a_new_managed_auth_config(composio):  # noqa: F811
    started = composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert started == composio_accounts.Started("ca_new", LINK_URL)
    assert composio.auth_configs.created == [("stripe", {"type": "use_composio_managed_auth"})]
    assert composio.connected_accounts.linked == [("org:o1", "ac_new", BACK)]


def test_start_reuses_the_newest_enabled_auth_config(composio):  # noqa: F811
    composio.auth_configs.items = [
        SimpleNamespace(id="ac_old", status="ENABLED", created_at="2026-01-01T00:00:00Z"),
        SimpleNamespace(id="ac_off", status="DISABLED", created_at="2026-09-01T00:00:00Z"),
        SimpleNamespace(id="ac_mine", status="ENABLED", created_at="2026-05-01T00:00:00Z"),
    ]
    composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert composio.auth_configs.queries == [{"toolkit_slug": "stripe"}]
    assert composio.auth_configs.created == []
    assert composio.connected_accounts.linked[0][1] == "ac_mine"


def test_start_adopts_an_account_that_is_already_active(composio):  # noqa: F811
    composio.connected_accounts.active = ["ca_old"]
    started = composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert started == composio_accounts.Started("ca_old", BACK)
    assert composio.connected_accounts.linked == []
    assert composio.connected_accounts.queries == [
        {"user_ids": ["org:o1"], "auth_config_ids": ["ac_new"], "statuses": ["ACTIVE"], "limit": 1}
    ]


def test_start_is_a_503_when_the_reported_active_account_is_not_listed(composio):  # noqa: F811
    composio.connected_accounts.fail_link = ComposioMultipleConnectedAccountsError("an ACTIVE account exists")
    with pytest.raises(ApiProblem) as err:
        composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert (err.value.status, err.value.code, err.value.detail) == (
        503,
        composio_accounts.SERVICE_DOWN,
        STRIPE_DOWN,
    )


def test_start_is_a_503_when_the_link_has_no_redirect_url(composio):  # noqa: F811
    composio.connected_accounts.redirect_url = None
    with pytest.raises(ApiProblem) as err:
        composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert (err.value.status, err.value.code, err.value.detail) == (
        503,
        composio_accounts.SERVICE_DOWN,
        STRIPE_DOWN,
    )


@pytest.mark.parametrize("call", sorted(CALLS))
def test_without_a_key_the_client_is_never_built_and_the_answer_is_409(call, monkeypatch):
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    monkeypatch.setattr(
        composio_accounts, "_client", lambda: pytest.fail("the SDK client was built without a key")
    )
    assert composio_accounts.available() is False
    with pytest.raises(ApiProblem) as err:
        CALLS[call]()
    assert (err.value.status, err.value.code) == (409, composio_accounts.UNAVAILABLE)
    assert (
        err.value.detail
        == "Real accounts cannot be connected in this workspace yet. Use simulated data instead."
    )


def test_a_composio_failure_is_a_503_without_its_message(composio):  # noqa: F811
    composio.connected_accounts.fail_link = RuntimeError("https://backend.composio.dev/secret-path")
    with pytest.raises(ApiProblem) as err:
        composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert (err.value.status, err.value.code, err.value.detail) == (
        503,
        composio_accounts.SERVICE_DOWN,
        STRIPE_DOWN,
    )


@pytest.mark.parametrize("step", ["fail_list", "fail_create"])
def test_an_auth_config_failure_is_a_503(step, composio):  # noqa: F811
    setattr(composio.auth_configs, step, RuntimeError("down"))
    with pytest.raises(ApiProblem) as err:
        composio_accounts.start("org:o1", "stripe", BACK, "Stripe")
    assert (err.value.status, err.value.code, err.value.detail) == (
        503,
        composio_accounts.SERVICE_DOWN,
        STRIPE_DOWN,
    )
    assert composio.connected_accounts.linked == []


def test_status_reads_the_account_and_a_missing_one_is_gone(composio):  # noqa: F811
    composio.connected_accounts.statuses["ca_1"] = "ACTIVE"
    assert composio_accounts.status("ca_1") == "ACTIVE"
    assert composio_accounts.status("ca_nope") == composio_accounts.GONE
    assert composio.connected_accounts.got == ["ca_1", "ca_nope"]


def test_status_when_composio_fails_is_a_503(composio):  # noqa: F811
    composio.connected_accounts.fail_get = RuntimeError("down")
    with pytest.raises(ApiProblem) as err:
        composio_accounts.status("ca_1")
    assert (err.value.status, err.value.code) == (503, composio_accounts.SERVICE_DOWN)


def test_remove_deletes_and_revokes_and_a_missing_account_counts_as_removed(composio):  # noqa: F811
    composio_accounts.remove("ca_1")
    assert composio.connected_accounts.deleted == [("ca_1", True)]
    composio.connected_accounts.fail_delete = NotFound("ca_2")
    composio_accounts.remove("ca_2")  # no error


def test_remove_surfaces_a_failure(composio):  # noqa: F811
    composio.connected_accounts.fail_delete = RuntimeError("down")
    with pytest.raises(ApiProblem) as err:
        composio_accounts.remove("ca_1")
    assert (err.value.status, err.value.code) == (503, composio_accounts.SERVICE_DOWN)


def test_account_ids_lists_every_account_of_the_user_for_the_toolkit(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_2"]
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1", "ca_2"]
    assert composio.connected_accounts.queries == [{**LISTING, "limit": 50}]


def test_account_ids_when_composio_fails_is_a_503(composio):  # noqa: F811
    composio.connected_accounts.fail_list = RuntimeError("down")
    with pytest.raises(ApiProblem) as err:
        composio_accounts.account_ids("org:o1", "stripe")
    assert (err.value.status, err.value.code) == (503, composio_accounts.SERVICE_DOWN)


def test_account_ids_follows_the_cursor_through_every_page(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1", "ca_2", "ca_3"]
    composio.connected_accounts.page_size = 2
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1", "ca_2", "ca_3"]
    assert composio.connected_accounts.queries == [
        {**LISTING, "limit": 50},
        {**LISTING, "limit": 50, "cursor": "2"},
    ]


def test_account_ids_leaves_out_accounts_that_hold_no_tokens(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_half", "ca_1", "ca_old"]
    composio.connected_accounts.statuses.update({"ca_half": "INITIATED", "ca_old": "EXPIRED"})
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1", "ca_old"]


def test_account_ids_stops_when_the_cursor_repeats(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1"]
    composio.connected_accounts.cursor_mode = "loop"
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]
    assert [q.get("cursor") for q in composio.connected_accounts.queries] == [None, "again"]


def test_account_ids_stops_after_fifty_pages(composio):  # noqa: F811
    composio.connected_accounts.held = ["ca_1"]
    composio.connected_accounts.cursor_mode = "endless"
    assert composio_accounts.account_ids("org:o1", "stripe") == ["ca_1"]
    assert len(composio.connected_accounts.queries) == 50
