"""The workspace's publisher profile (sub-project D): the name its listings show in other workspaces'
marketplaces, a short description and simulated payout details. Only owners and admins see publishing: they
read and change the profile, the listings and the earnings. Turning publishing off blocks new submissions
only: the row (and so the name on listings) stays."""

from typing import Any

from app import db
from app.auth import Actor
from app.errors import TITLES, ApiProblem, Problem
from app.models.publishing import PublisherProfile, PublisherRequest, PublisherSettings
from app.store import iso

MANAGER_ROLES = frozenset({"owner", "admin"})

# The 403 of a publishing route: members get POLICY_DENIED, another workspace TENANT_SCOPE_DENIED.
MANAGERS_ONLY: dict[int | str, dict[str, Any]] = {
    403: {"model": Problem, "description": f"{TITLES[403]} (POLICY_DENIED: owners and admins only)."}
}


def require_manager(actor: Actor) -> None:
    if actor.role not in MANAGER_ROLES:
        raise ApiProblem(403, "POLICY_DENIED", "Only owners and admins can publish to the marketplace.")


def row(conn, org_id: str) -> dict | None:
    return conn.execute(
        "SELECT org_id, name, description, payout_note, enabled, updated_at "
        "FROM publishers WHERE org_id = %s",
        (org_id,),
    ).fetchone()


def active(conn, org_id: str) -> dict | None:
    found = row(conn, org_id)
    return found if found and found["enabled"] else None


def _settings(found: dict | None) -> PublisherSettings:
    if found is None:
        return PublisherSettings(enabled=False)
    return PublisherSettings(
        enabled=bool(found["enabled"]),
        profile=PublisherProfile(
            name=found["name"],
            description=found["description"],
            payout_note=found["payout_note"],
            updated_at=iso(found["updated_at"]),
        ),
    )


def settings(org_id: str) -> PublisherSettings:
    with db.connect() as conn:
        return _settings(row(conn, org_id))


def save(actor: Actor, body: PublisherRequest) -> PublisherSettings:
    require_manager(actor)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO publishers (org_id, name, description, payout_note) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (org_id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, "
            "payout_note = EXCLUDED.payout_note, enabled = true, updated_at = now()",
            (actor.org_id, body.name, body.description, body.payout_note),
        )
        conn.commit()
        return _settings(row(conn, actor.org_id))


def disable(actor: Actor) -> PublisherSettings:
    require_manager(actor)
    with db.connect() as conn:
        conn.execute(
            "UPDATE publishers SET enabled = false, updated_at = now() WHERE org_id = %s", (actor.org_id,)
        )
        conn.commit()
        return _settings(row(conn, actor.org_id))
