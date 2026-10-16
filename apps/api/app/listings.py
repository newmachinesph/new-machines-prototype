"""Listings (sub-project D): a workspace's own agent or pack listed in every other workspace's marketplace,
and the review of each of its versions.

A version moves checking -> in_review -> approved | changes_requested | rejected; a failed automatic check
ends it in checks_failed before ops sees it. One version per listing is open (checking or in_review) at a
time. A listing is pending until a version is approved, then listed; ops unlists and relists it.
`listed_definitions` holds exactly the current approved bundle of every listed listing: what other workspaces
see.

Functions run on the caller's connection and do not commit.
"""

import secrets
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from app import ops_state
from app.defs import owners, registry
from app.models.common import Money
from app.models.ops import OpsRole
from app.models.publishing import ListingCheck, ListingVersion
from app.runtime.projection import TERMINAL_RUN_STATUSES
from app.store import iso

OPEN = ("checking", "in_review")
DECISIONS = {"approve": "approved", "request-changes": "changes_requested", "reject": "rejected"}
MOVES = {"unlist": ("listed", "unlisted"), "relist": ("unlisted", "listed")}
SANDBOX_PASSED = "The sandbox run completed."
SANDBOX_FAILED = "The sandbox run ended {status}. Open it to see why, fix the definition and submit again."

_LISTING = (
    "SELECT l.*, COALESCE(p.name, o.name) AS publisher FROM listings l "
    "JOIN orgs o ON o.id = l.publisher_org_id LEFT JOIN publishers p ON p.org_id = l.publisher_org_id"
)
_VERSION = (
    "SELECT id, definition_version, status, price_minor, checks, submitted_at, submitted_by, decided_at, "
    "decided_by, note FROM listing_versions"
)
_IN_REVIEW = (
    "WHERE EXISTS (SELECT 1 FROM listing_versions v WHERE v.listing_id = l.id AND v.status = 'in_review')"
)


class SubmissionOpen(Exception):
    """A version of the listing is already checking or waiting for review."""


class Transition(Exception):
    """The listing cannot make this move now; the message says why."""


@dataclass(frozen=True)
class MarketRow:
    listing_id: str
    kind: str
    key: str
    name: str
    publisher: str
    publisher_org_id: str
    price_minor: int
    version: int  # the approved definition version
    version_id: str  # the approved listing version (`listings.current_version_id`)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


# --- reads ----------------------------------------------------------------------------------------------


def get(conn, listing_id: str) -> dict | None:
    return conn.execute(f"{_LISTING} WHERE l.id = %s", (listing_id,)).fetchone()


def find(conn, kind: str, key: str) -> dict | None:
    return conn.execute(f"{_LISTING} WHERE l.kind = %s AND l.definition_key = %s", (kind, key)).fetchone()


def for_publisher(conn, org_id: str) -> list[dict]:
    return conn.execute(
        f"{_LISTING} WHERE l.publisher_org_id = %s ORDER BY l.updated_at DESC, l.id", (org_id,)
    ).fetchall()


def for_ops(conn, status: str | None) -> list[dict]:
    """Every listing, newest change first. `in_review`: a version waits for a decision; `pending`, `listed`,
    `unlisted`: the listing's status."""
    if status == "in_review":
        where, params = _IN_REVIEW, ()
    elif status is not None:
        where, params = "WHERE l.status = %s", (status,)
    else:
        where, params = "", ()
    return conn.execute(f"{_LISTING} {where} ORDER BY l.updated_at DESC, l.id", params).fetchall()


def version_of(row: dict) -> ListingVersion:
    return ListingVersion(
        id=row["id"],
        definition_version=row["definition_version"],
        status=row["status"],
        price=Money(amount_minor=int(row["price_minor"])),
        checks=[ListingCheck.model_validate(c) for c in row["checks"] or []],
        submitted_at=iso(row["submitted_at"]),
        submitted_by=row["submitted_by"],
        decided_at=iso(row["decided_at"]) if row["decided_at"] else None,
        decided_by=row["decided_by"],
        note=row["note"] or None,
    )


def versions(conn, listing_id: str) -> list[ListingVersion]:
    rows = conn.execute(
        f"{_VERSION} WHERE listing_id = %s ORDER BY submitted_at DESC, definition_version DESC, id DESC",
        (listing_id,),
    ).fetchall()
    return [version_of(r) for r in rows]


def open_version(conn, listing_id: str) -> ListingVersion | None:
    row = conn.execute(
        f"{_VERSION} WHERE listing_id = %s AND status = ANY(%s)", (listing_id, list(OPEN))
    ).fetchone()
    return version_of(row) if row else None


def market_info(conn, viewer_org_id: str) -> dict[tuple[str, str], MarketRow]:
    """Every listed agent and pack of another workspace, by (kind, definition key), at its approved
    version. Only a listing whose publisher owns the definition privately counts (the trusted rule of
    `registry.latest_visible`): a listing naming a platform key or another org's is never shown."""
    rows = conn.execute(
        "SELECT l.id, l.kind, l.definition_key, l.name, COALESCE(p.name, o.name) AS publisher, "
        "l.publisher_org_id, v.id AS version_id, v.price_minor, v.definition_version FROM listings l "
        "JOIN listing_versions v ON v.id = l.current_version_id JOIN orgs o ON o.id = l.publisher_org_id "
        "JOIN definition_owners d ON d.kind = l.kind AND d.key = l.definition_key AND d.owner_kind = 'org' "
        "AND d.owner_id = l.publisher_org_id AND d.visibility = 'private' "
        "LEFT JOIN publishers p ON p.org_id = l.publisher_org_id "
        "WHERE l.status = 'listed' AND l.publisher_org_id <> %s",
        (viewer_org_id,),
    ).fetchall()
    return {
        (r["kind"], r["definition_key"]): MarketRow(
            listing_id=r["id"],
            kind=r["kind"],
            key=r["definition_key"],
            name=r["name"],
            publisher=r["publisher"],
            publisher_org_id=r["publisher_org_id"],
            price_minor=int(r["price_minor"]),
            version=int(r["definition_version"]),
            version_id=r["version_id"],
        )
        for r in rows
    }


# --- writes ---------------------------------------------------------------------------------------------


def submit(
    conn,
    *,
    kind: str,
    key: str,
    publisher_org_id: str,
    name: str,
    definition_version: int,
    definitions: list[dict],
    price_minor: int,
    checks: list[dict],
    status: str,
    submitted_by: str,
    check_run_id: str | None = None,
    check_input: dict | None = None,
) -> tuple[str, str]:
    """Record a submitted version (creating the listing on the first one). SubmissionOpen while another
    version is open. Transition unless the publisher owns the definition privately (never a platform key or
    another org's). Returns (listing id, version id)."""
    if status not in OPEN:
        raise ValueError(f"a submission starts checking or in review, not {status}")
    if registry.owner_of(conn, kind, key) != owners.org_owner(publisher_org_id):
        raise Transition(f"{kind}/{key} is not a private definition of this workspace.")
    conn.execute(
        "INSERT INTO listings (id, kind, definition_key, publisher_org_id, name) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (kind, definition_key) DO NOTHING",
        (new_id("lst"), kind, key, publisher_org_id, name),
    )
    listing = conn.execute(
        "SELECT id, publisher_org_id FROM listings WHERE kind = %s AND definition_key = %s FOR NO KEY UPDATE",
        (kind, key),
    ).fetchone()
    if listing["publisher_org_id"] != publisher_org_id:
        raise ValueError(f"{kind}/{key} is listed by another workspace")
    if open_version(conn, listing["id"]) is not None:
        raise SubmissionOpen("A version of this is already waiting for review.")
    version_id = new_id("lsv")
    conn.execute(
        "INSERT INTO listing_versions (id, listing_id, definition_version, definitions, price_minor, status, "
        "checks, check_run_id, check_input, submitted_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            version_id,
            listing["id"],
            definition_version,
            Jsonb(definitions),
            price_minor,
            status,
            Jsonb(checks),
            check_run_id,
            Jsonb(check_input) if check_input is not None else None,
            submitted_by,
        ),
    )
    conn.execute("UPDATE listings SET updated_at = now() WHERE id = %s", (listing["id"],))
    return listing["id"], version_id


def settle_checks(conn, org_id: str | None = None) -> int:
    """Move every checking version whose sandbox run has ended (of `org_id`'s listings, or all): to in_review
    when the run completed, to checks_failed otherwise; each moved version's listing counts as changed.
    Returns how many moved.

    It locks the moved versions' listings (in id order, as `decide` and `move` do), so callers commit after it
    and before any other listing write (submit, decide, move)."""
    rows = conn.execute(
        "SELECT v.id, v.listing_id, v.checks, v.check_run_id, r.status AS run_status FROM listing_versions v "
        "JOIN listings l ON l.id = v.listing_id JOIN runs r ON r.id = v.check_run_id "
        "WHERE v.status = 'checking' AND r.status = ANY(%(done)s) "
        "AND (%(org)s::text IS NULL OR l.publisher_org_id = %(org)s) FOR UPDATE OF v SKIP LOCKED",
        {"done": sorted(TERMINAL_RUN_STATUSES), "org": org_id},
    ).fetchall()
    conn.execute(
        "SELECT id FROM listings WHERE id = ANY(%s) ORDER BY id FOR NO KEY UPDATE",
        (sorted({r["listing_id"] for r in rows}),),
    ).fetchall()
    for row in rows:
        passed = row["run_status"] == "COMPLETED"
        sandbox = {
            "name": "sandbox",
            "state": "passed" if passed else "failed",
            "detail": SANDBOX_PASSED if passed else SANDBOX_FAILED.format(status=row["run_status"].lower()),
            "run_id": row["check_run_id"],
        }
        checks = [c for c in row["checks"] or [] if c.get("name") != "sandbox"] + [sandbox]
        conn.execute(
            "UPDATE listing_versions SET status = %s, checks = %s WHERE id = %s",
            ("in_review" if passed else "checks_failed", Jsonb(checks), row["id"]),
        )
        conn.execute("UPDATE listings SET updated_at = now() WHERE id = %s", (row["listing_id"],))
    return len(rows)


def _locked(conn, listing_id: str) -> dict:
    """Lock every listing of `listing_id`'s publisher, in id order, then return the listing. Decisions and
    moves of one publisher's listings run one at a time (the shared-definition check reads its other
    listings), and the fixed order means two of them cannot deadlock."""
    owner = conn.execute("SELECT publisher_org_id FROM listings WHERE id = %s", (listing_id,)).fetchone()
    if owner is None:
        raise LookupError(f"No listing {listing_id}.")
    conn.execute(
        "SELECT id FROM listings WHERE publisher_org_id = %s ORDER BY id FOR NO KEY UPDATE",
        (owner["publisher_org_id"],),
    ).fetchall()
    return conn.execute("SELECT * FROM listings WHERE id = %s FOR NO KEY UPDATE", (listing_id,)).fetchone()


def decide(
    conn, listing_id: str, verb: str, actor_email: str, note: str, *, actor_role: OpsRole | None = None
) -> None:
    """Decide the version in review: approve (it becomes the listed version; an unlisted listing stays
    unlisted), request changes or reject (both need a note). Audited. Transition, before anything changes,
    when approving would change the version of a definition another listed listing shares."""
    target = DECISIONS[verb]
    listing = _locked(conn, listing_id)
    version = conn.execute(
        "SELECT id, definition_version, price_minor, definitions FROM listing_versions "
        "WHERE listing_id = %s AND status = 'in_review' FOR UPDATE",
        (listing_id,),
    ).fetchone()
    if version is None:
        raise Transition(f"{listing['name']} has no version waiting for review.")
    if verb != "approve" and not note.strip():
        raise Transition("A note is required to request changes or reject.")
    if verb == "approve" and listing["status"] != "unlisted":
        _check_shared(conn, listing_id, version["definitions"])
    conn.execute(
        "UPDATE listing_versions SET status = %s, decided_at = now(), decided_by = %s, note = %s "
        "WHERE id = %s",
        (target, actor_email, note, version["id"]),
    )
    if verb == "approve":
        status = "unlisted" if listing["status"] == "unlisted" else "listed"
        defined = registry.get_version(
            conn, listing["kind"], listing["definition_key"], version["definition_version"]
        )
        name = str((defined.body if defined else {}).get("name") or listing["name"])
        conn.execute(
            "UPDATE listings SET status = %s, current_version_id = %s, price_minor = %s, name = %s, "
            "updated_at = now() WHERE id = %s",
            (status, version["id"], version["price_minor"], name, listing_id),
        )
        if status == "listed":
            expose(conn, listing_id)
    else:
        conn.execute("UPDATE listings SET updated_at = now() WHERE id = %s", (listing_id,))
    summary = f"Version {version['definition_version']}: {target.replace('_', ' ')}"
    ops_state.audit(
        conn,
        actor_email,
        f"listing.{verb}",
        "listing",
        listing_id,
        note,
        {"summary": summary},
        actor_role=actor_role,
    )


def move(
    conn, listing_id: str, verb: str, actor_email: str, reason: str, *, actor_role: OpsRole | None = None
) -> None:
    """Unlist a listed listing or relist an unlisted one. Audited. Relisting refuses (Transition, before
    anything changes) a bundle that would change the version of a definition another listed listing shares."""
    before, after = MOVES[verb]
    listing = _locked(conn, listing_id)
    if listing["status"] != before:
        raise Transition(f"A {listing['status']} listing cannot be moved with {verb}.")
    if after == "listed":
        expose(conn, listing_id)  # checks the shared definitions first; the status is not read
    conn.execute("UPDATE listings SET status = %s, updated_at = now() WHERE id = %s", (after, listing_id))
    if after != "listed":
        withdraw(conn, listing_id)
    ops_state.audit(
        conn,
        actor_email,
        f"listing.{verb}",
        "listing",
        listing_id,
        reason,
        {"summary": f"Status {before} → {after}"},
        actor_role=actor_role,
    )


def _check_shared(conn, listing_id: str, definitions: list[dict]) -> None:
    """Transition when another listed listing of the same publisher has a definition of `definitions` in its
    current approved bundle at another version: `listed_definitions` holds one version per definition, so
    both listings must use the same one. Reads the bundles, not `listed_definitions`, so it does not matter
    which listing's row holds a shared definition."""
    wanted = {(d["kind"], d["key"]): d["version"] for d in definitions}
    rows = conn.execute(
        "SELECT x->>'kind' AS kind, x->>'key' AS key, (x->>'version')::int AS version, l.name "
        "FROM listings l JOIN listing_versions v ON v.id = l.current_version_id "
        "CROSS JOIN LATERAL jsonb_array_elements(v.definitions) x "
        "WHERE l.status = 'listed' AND l.id <> %(id)s "
        "AND l.publisher_org_id = (SELECT publisher_org_id FROM listings WHERE id = %(id)s) ORDER BY l.id",
        {"id": listing_id},
    ).fetchall()
    for r in rows:
        ours = wanted.get((r["kind"], r["key"]))
        if ours is not None and r["version"] != ours:
            raise Transition(
                f"{r['kind']} {r['key']} is listed at version {r['version']} with {r['name']}. Resubmit "
                f"{r['name']} with version {ours} of it first, so both use the same version."
            )


def withdraw(conn, listing_id: str) -> None:
    """Remove the listing's rows from `listed_definitions`, then put back the current bundles of the
    publisher's other listed listings, so a definition they share with it stays exposed."""
    conn.execute("DELETE FROM listed_definitions WHERE listing_id = %s", (listing_id,))
    conn.execute(
        "INSERT INTO listed_definitions (kind, key, version, listing_id, publisher_org_id) "
        "SELECT d->>'kind', d->>'key', (d->>'version')::int, l.id, l.publisher_org_id FROM listings l "
        "JOIN listing_versions v ON v.id = l.current_version_id "
        "CROSS JOIN LATERAL jsonb_array_elements(v.definitions) d "
        "WHERE l.status = 'listed' AND l.id <> %(id)s "
        "AND l.publisher_org_id = (SELECT publisher_org_id FROM listings WHERE id = %(id)s) "
        "ON CONFLICT (kind, key) DO NOTHING",
        {"id": listing_id},
    )


def expose(conn, listing_id: str) -> None:
    """Write the current approved version's bundle into `listed_definitions`, replacing the listing's rows. A
    definition another listed listing already exposes at the same version keeps that row; at another version,
    Transition before anything changes. Nothing when the listing has no approved version."""
    row = conn.execute(
        "SELECT l.publisher_org_id, v.definitions FROM listings l JOIN listing_versions v "
        "ON v.id = l.current_version_id WHERE l.id = %s",
        (listing_id,),
    ).fetchone()
    if row is None:
        return
    _check_shared(conn, listing_id, row["definitions"])
    withdraw(conn, listing_id)
    for d in row["definitions"]:
        conn.execute(
            "INSERT INTO listed_definitions (kind, key, version, listing_id, publisher_org_id) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (kind, key) DO NOTHING",
            (d["kind"], d["key"], d["version"], listing_id, row["publisher_org_id"]),
        )
