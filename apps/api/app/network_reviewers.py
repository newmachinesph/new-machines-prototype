"""A user's profile as a New Machines network reviewer (live workspace): their own switch "Review for the
network", and the name, languages and skills New Machines uses to offer them tasks. One row per user, never
read by another user; operators suspend and reinstate it (`app.ops_reviewers`)."""

from app import db, run_tasks
from app.auth import Actor
from app.models.workforce import NetworkProfile, NetworkProfileRequest

_COLUMNS = "name, languages, skills, enabled, status"
_UPSERT = (
    "INSERT INTO network_reviewers (user_id, email, name, languages, skills, enabled) "
    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET "
    "email = COALESCE(NULLIF(EXCLUDED.email, ''), network_reviewers.email), name = EXCLUDED.name, "
    "languages = EXCLUDED.languages, skills = EXCLUDED.skills, "
    f"enabled = EXCLUDED.enabled, updated_at = now() RETURNING {_COLUMNS}"
)


def _unique(items: list[str]) -> list[str]:
    """Each entry once, compared without case, the first spelling kept."""
    seen: set[str] = set()
    out = []
    for item in items:
        if item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    return out


def _profile(row: dict) -> NetworkProfile:
    return NetworkProfile(
        enabled=bool(row["enabled"]),
        suspended=row["status"] == "suspended",
        name=row["name"],
        languages=list(row["languages"]),
        skills=list(row["skills"]),
    )


def profile(actor: Actor) -> NetworkProfile:
    """The user's profile; before they ever turn it on, an empty one under their sign-in name."""
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM network_reviewers WHERE user_id = %s", (actor.user_id,)
        ).fetchone()
    if row is None:
        return NetworkProfile(enabled=False, suspended=False, name=actor.name or "", languages=[], skills=[])
    return _profile(row)


def update(actor: Actor, body: NetworkProfileRequest) -> NetworkProfile:
    """Save the profile and the user's switch. Turning it off returns the open tasks they claimed through the
    network to the queue. A suspension by New Machines stays in place whatever the user saves. A later
    sign-in without an email keeps the email stored. The upsert locks the profile row before the release
    touches any task: the lock order of `app.review_routing`."""
    params = (
        actor.user_id,
        actor.email or "",
        body.name,
        _unique(body.languages),
        _unique(body.skills),
        body.enabled,
    )
    with db.connect() as conn:
        row = conn.execute(_UPSERT, params).fetchone()
        if not body.enabled:
            run_tasks.release_claims(conn, user_id=actor.user_id, via="network")
        conn.commit()
    return _profile(row)
