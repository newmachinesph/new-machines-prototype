"""Sub-project D, part 6: the publisher profile. Owners and admins turn publishing on and off, and only they
see publishing at all; no workspace reads or changes another's."""

import pytest

from tests.test_live_catalog import _rows, ana, ben, live, starts  # noqa: F401

LISTING = "lst_000000000000"
PROFILE = {"name": "  Acme Labs ", "description": "Finance agents.", "payoutNote": "Bank ending 1234"}


def _path(user, org_id: str | None = None) -> str:
    return f"/v1/organizations/{org_id or user.org_id}/publisher"


def test_publishing_starts_off(ana):  # noqa: F811
    res = ana.get(_path(ana))
    assert res.status_code == 200
    assert res.json() == {"enabled": False, "simulated": True}


def test_an_owner_turns_publishing_on_and_off(ana, db):  # noqa: F811
    on = ana.api.put(_path(ana), json=PROFILE, headers=ana.headers).json()
    assert on["enabled"] is True and on["profile"]["name"] == "Acme Labs"
    assert on["profile"]["payoutNote"] == "Bank ending 1234" and on["simulated"] is True
    off = ana.delete(_path(ana)).json()
    assert off["enabled"] is False and off["profile"]["name"] == "Acme Labs"  # kept for its listings
    again = ana.api.put(_path(ana), json={"name": "Acme"}, headers=ana.headers).json()
    assert again["enabled"] is True and again["profile"]["name"] == "Acme"
    assert _rows(db, "SELECT count(*) AS n FROM publishers")[0]["n"] == 1


def test_only_owners_and_admins_change_the_profile(ana, db):  # noqa: F811
    db.execute("UPDATE org_members SET role = 'member' WHERE user_id = 'uid_ana'")
    db.commit()
    res = ana.api.put(_path(ana), json=PROFILE, headers=ana.headers)
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED"
    assert ana.delete(_path(ana)).status_code == 403


@pytest.mark.parametrize(
    "route", ["publisher", "studio/listings", f"studio/listings/{LISTING}", "studio/earnings"]
)
def test_a_member_cannot_read_publishing(ana, db, route):  # noqa: F811
    ana.api.put(_path(ana), json=PROFILE, headers=ana.headers)
    db.execute("UPDATE org_members SET role = 'member' WHERE user_id = 'uid_ana'")
    db.commit()
    res = ana.get(f"/v1/organizations/{ana.org_id}/{route}")
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED", res.text


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owners_and_admins_read_publishing(ana, db, role):  # noqa: F811
    db.execute("UPDATE org_members SET role = %s WHERE user_id = 'uid_ana'", (role,))
    db.commit()
    for route in ("publisher", "studio/listings", "studio/earnings"):
        assert ana.get(f"/v1/organizations/{ana.org_id}/{route}").status_code == 200, route


def test_another_workspace_cannot_read_or_change_the_profile(ana, ben):  # noqa: F811
    ana.api.put(_path(ana), json=PROFILE, headers=ana.headers)
    for res in (
        ben.get(_path(ben, ana.org_id)),
        ben.api.put(_path(ben, ana.org_id), json=PROFILE, headers=ben.headers),
        ben.delete(_path(ben, ana.org_id)),
    ):
        assert res.status_code == 403 and res.json()["code"] == "TENANT_SCOPE_DENIED"
    assert ben.get(_path(ben)).json()["enabled"] is False


def test_a_blank_name_is_refused(ana):  # noqa: F811
    res = ana.api.put(_path(ana), json={"name": "   "}, headers=ana.headers)
    assert res.status_code == 422
