"""Postgres-backed, append-only version registry for definitions.

Every function runs on the caller's connection and never commits: the caller owns the transaction.
"""

import json
import logging
import secrets
from dataclasses import dataclass

import yaml
from psycopg.types.json import Jsonb

from app.defs import owners
from app.defs.digest import digest
from app.defs.model import Bundle, Definition, path_for

_ADVISORY_LOCK = 7_204_100_001  # serialises concurrent version inserts
FILE, CONSOLE, BUILDER = "file", "console", "builder"  # definition_versions.source

log = logging.getLogger(__name__)


class NoChange(Exception):
    """The published definition is identical (same digest) to the latest version."""


class VersionConflict(Exception):
    """The latest version is not the one the edit started from: someone published in between."""

    def __init__(self, latest: int, base: int) -> None:
        super().__init__(f"latest is v{latest}, the edit started from v{base}")
        self.latest = latest
        self.base = base


class KeyTaken(Exception):
    """The kind/key already belongs to another owner, or to the platform."""


@dataclass(frozen=True)
class Version:
    kind: str
    key: str
    version: int
    digest: str
    body: dict
    files: dict[str, str]
    source: str
    published_by: str
    reason: str
    published_at: str


_COLUMNS = "kind, key, version, digest, body, files, source, published_by, reason, published_at"


def _version(row: dict) -> Version:
    return Version(
        kind=row["kind"],
        key=row["key"],
        version=row["version"],
        digest=row["digest"],
        body=row["body"],
        files=row["files"],
        source=row["source"],
        published_by=row["published_by"],
        reason=row["reason"],
        published_at=row["published_at"].isoformat(),
    )


def latest(conn, kind: str, key: str) -> Version | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM definition_versions WHERE kind = %s AND key = %s "
        "ORDER BY version DESC LIMIT 1",
        (kind, key),
    ).fetchone()
    return _version(row) if row else None


def latest_all(conn) -> list[Version]:
    rows = conn.execute(
        f"SELECT DISTINCT ON (kind, key) {_COLUMNS} FROM definition_versions ORDER BY kind, key, version DESC"
    ).fetchall()
    return [_version(r) for r in rows]


def latest_of_kind(conn, kind: str) -> list[Version]:
    """The latest version of every definition of `kind`, by key: what `latest` (and so a run snapshot)
    resolves each key to."""
    rows = conn.execute(
        f"SELECT DISTINCT ON (key) {_COLUMNS} FROM definition_versions WHERE kind = %s "
        "ORDER BY key, version DESC",
        (kind,),
    ).fetchall()
    return [_version(r) for r in rows]


def versions(conn, kind: str, key: str) -> list[Version]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM definition_versions WHERE kind = %s AND key = %s ORDER BY version DESC",
        (kind, key),
    ).fetchall()
    return [_version(r) for r in rows]


def get_version(conn, kind: str, key: str, version: int) -> Version | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM definition_versions WHERE kind = %s AND key = %s AND version = %s",
        (kind, key, version),
    ).fetchone()
    return _version(row) if row else None


def _latest_file(conn, kind: str, key: str) -> Version | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM definition_versions WHERE kind = %s AND key = %s AND source = %s "
        "ORDER BY version DESC LIMIT 1",
        (kind, key, FILE),
    ).fetchone()
    return _version(row) if row else None


def _console_wins(conn, d: Definition, dig: str, current: Version) -> bool:
    """A file apply never silently replaces a console publish. When the file is unchanged since it was last
    applied there is nothing to do; when it changed, the console version still stays and a warning says so."""
    if current.source == FILE:
        return False
    applied = _latest_file(conn, d.kind, d.key)
    if applied is None or applied.digest != dig:
        log.warning(
            "%s/%s: v%d was published from the console, so the changed file is not applied "
            "(python -m app.defs apply --force replaces it).",
            d.kind,
            d.key,
            current.version,
        )
    return True


def lock(conn) -> None:
    """Take the registry's transaction lock, as every version insert does. Postgres advisory locks are
    re-entrant within a session, so a caller may hold it around several inserts; it is released at commit."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK,))


def _insert(
    conn,
    d: Definition,
    source: str,
    actor: str,
    reason: str,
    *,
    keep_console: bool = False,
    base_version: int | None = None,
) -> Version | None:
    """Insert the next version of `d`, or return None when its digest equals the latest, or when
    `keep_console` is set and the latest version came from the console. Raises VersionConflict when
    `base_version` is given and is not the latest version (0: none yet), checked under the lock."""
    lock(conn)
    current = latest(conn, d.kind, d.key)
    if base_version is not None and (current.version if current else 0) != base_version:
        raise VersionConflict(current.version if current else 0, base_version)
    dig = digest(d)
    if current is not None and current.digest == dig:
        return None
    if keep_console and current is not None and _console_wins(conn, d, dig, current):
        return None
    row = conn.execute(
        "INSERT INTO definition_versions "
        "(kind, key, version, digest, body, files, source, published_by, reason) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
        (
            d.kind,
            d.key,
            (current.version + 1) if current else 1,
            dig,
            Jsonb(d.body),
            Jsonb(d.files),
            source,
            actor,
            reason,
        ),
    ).fetchone()
    return _version(row)


def _seed_memory(conn, bundle: Bundle, actor: str) -> None:
    """Make each space's shared seed rows (source 'seed', no org) equal its file's `seed_items`: a seed the
    file no longer lists (moved or reworded) is retired, and every listed seed that is missing is added.
    Items an org or an operator added are never touched. A space whose latest version was published from the
    console is skipped, as `apply_bundle` leaves that version itself: its file no longer defines the space."""
    for space in bundle.of("memory_space"):
        current = latest(conn, space.kind, space.key)
        if current is not None and current.source != FILE:
            log.info(
                "%s/%s: v%d was published from the console, so its file's seed_items are not synced.",
                space.kind,
                space.key,
                current.version,
            )
            continue
        items = list(dict.fromkeys(space.body.get("seed_items") or []))
        conn.execute(
            "DELETE FROM memory_items WHERE space = %s AND source = 'seed' AND org_id IS NULL "
            "AND NOT (text = ANY(%s))",
            (space.key, items),
        )
        rows = conn.execute(
            "SELECT text FROM memory_items WHERE space = %s AND source = 'seed' AND org_id IS NULL",
            (space.key,),
        ).fetchall()
        present = {r["text"] for r in rows}
        for text in items:
            if text in present:
                continue
            conn.execute(
                "INSERT INTO memory_items (id, space, text, source, created_by) VALUES (%s, %s, %s, %s, %s)",
                (f"mem_{secrets.token_hex(6)}", space.key, text, "seed", actor),
            )


def apply_bundle(
    conn, bundle: Bundle, actor: str = "definitions-apply", *, force: bool = False
) -> list[Version]:
    """Insert a new version per definition whose digest differs from its latest; sync seed memory items.

    A definition whose latest version was published from the console is left alone (with a warning when its
    file changed since the last apply), so restarting the API never reverts an operator's edit; `force`
    applies the file over it. Runs on `conn` without committing; the caller commits. Returns only the
    versions it created.
    """
    created = [
        v
        for d in sorted(bundle.items.values(), key=lambda d: (d.kind, d.key))
        if (v := _insert(conn, d, FILE, actor, "definitions apply", keep_console=not force)) is not None
    ]
    _seed_memory(conn, bundle, actor)
    return created


def publish(
    conn,
    d: Definition,
    actor: str,
    reason: str,
    *,
    base_version: int | None = None,
    source: str = CONSOLE,
) -> Version:
    """Publish an edit as the next version (source "console" unless given). Does not commit.

    Raises VersionConflict when `base_version` is given and is not the latest version, and NoChange when
    the digest equals the latest version's.
    """
    v = _insert(conn, d, source, actor, reason, base_version=base_version)
    if v is None:
        raise NoChange(f"{d.kind}/{d.key} is unchanged")
    return v


def publish_if_changed(conn, d: Definition, actor: str, reason: str, *, source: str) -> Version | None:
    """Insert the next version of `d`, or return None when it equals the latest. Does not commit."""
    return _insert(conn, d, source, actor, reason)


def _bundle(versions: list[Version]) -> Bundle:
    return Bundle(
        items={
            (v.kind, v.key): Definition(
                kind=v.kind, key=v.key, body=v.body, files=v.files, path=path_for(v.kind, v.key)
            )
            for v in versions
        }
    )


def latest_bundle(conn) -> Bundle:
    return _bundle(latest_all(conn))


def export_files(v: Version) -> dict[str, str]:
    """Files of a version as {path relative to the definitions root: text}."""
    path = path_for(v.kind, v.key)
    if v.kind == "schema":
        return {path: json.dumps(v.body, indent=2, ensure_ascii=False) + "\n"}
    text = yaml.safe_dump(
        {"kind": v.kind, "key": v.key, **v.body}, sort_keys=False, allow_unicode=True, width=100
    )
    out = {path: text}
    if v.kind == "agent":
        folder = path.rsplit("/", 1)[0]
        out.update({f"{folder}/{rel}": content for rel, content in v.files.items()})
    return out


# --- owners and visibility --------------------------------------------------------------------------


def owner_of(conn, kind: str, key: str) -> owners.Owner:
    """Who owns kind/key: its definition_owners row, else the platform."""
    row = conn.execute(
        "SELECT owner_kind, owner_id, visibility FROM definition_owners WHERE kind = %s AND key = %s",
        (kind, key),
    ).fetchone()
    if row is None:
        return owners.PLATFORM
    return owners.Owner(row["owner_kind"], row["owner_id"], row["visibility"])


def claim(conn, kind: str, key: str, owner: owners.Owner, created_by: str) -> None:
    """Record `owner` for kind/key before its first version. Claiming a key the same owner already holds does
    nothing. KeyTaken when another owner holds it, or when it already has versions without an owner (the
    platform's). Takes the registry lock, so two claims of one key serialise. Does not commit."""
    lock(conn)
    current = conn.execute(
        "SELECT owner_kind, owner_id FROM definition_owners WHERE kind = %s AND key = %s", (kind, key)
    ).fetchone()
    if current is not None:
        if (current["owner_kind"], current["owner_id"]) != (owner.kind, owner.id):
            raise KeyTaken(f"{kind}/{key} belongs to another owner")
        return
    if latest(conn, kind, key) is not None:
        raise KeyTaken(f"{kind}/{key} is a platform definition")
    conn.execute(
        "INSERT INTO definition_owners (kind, key, owner_kind, owner_id, visibility, created_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (kind, key, owner.kind, owner.id, owner.visibility, created_by),
    )


_V_COLUMNS = ", ".join(f"v.{c}" for c in _COLUMNS.split(", "))
# A version row `v` that %(org)s may not see: privately owned by anyone but that org.
_HIDDEN = (
    "EXISTS (SELECT 1 FROM definition_owners o WHERE o.kind = v.kind AND o.key = v.key "
    "AND o.visibility = 'private' AND (o.owner_kind <> 'org' OR o.owner_id IS DISTINCT FROM %(org)s))"
)


def latest_visible(conn, org_id: str | None) -> list[Version]:
    """The latest version of every definition `org_id` may see: the platform's, marketplace ones, and the
    org's own private ones. None sees no org's private definitions (the ops console, the file export)."""
    rows = conn.execute(
        f"SELECT DISTINCT ON (v.kind, v.key) {_V_COLUMNS} FROM definition_versions v WHERE NOT {_HIDDEN} "
        "ORDER BY v.kind, v.key, v.version DESC",
        {"org": org_id},
    ).fetchall()
    return [_version(r) for r in rows]


# A version row `v` that an org or a developer owns (`owner_of(...).kind != "platform"`).
_NOT_PLATFORM = (
    "EXISTS (SELECT 1 FROM definition_owners o WHERE o.kind = v.kind AND o.key = v.key "
    "AND o.owner_kind <> 'platform')"
)


def latest_platform(conn) -> list[Version]:
    """The latest version of every platform definition, by kind then key: what the ops console lists and the
    file export writes. The same rule as `owner_of(...).kind == "platform"`, so list, detail and export
    agree. Unlike `latest_visible(conn, None)`, it leaves out an org's marketplace definitions too."""
    rows = conn.execute(
        f"SELECT DISTINCT ON (v.kind, v.key) {_V_COLUMNS} FROM definition_versions v "
        f"WHERE NOT {_NOT_PLATFORM} ORDER BY v.kind, v.key, v.version DESC"
    ).fetchall()
    return [_version(r) for r in rows]


def visible_bundle(conn, org_id: str | None) -> Bundle:
    """`latest_visible` as a Bundle: what an edit by `org_id` is validated against."""
    return _bundle(latest_visible(conn, org_id))


def owned(conn, org_id: str, kind: str) -> list[Version]:
    """The latest version of every definition of `kind` the org owns, by key."""
    rows = conn.execute(
        f"SELECT DISTINCT ON (v.key) {_V_COLUMNS} FROM definition_versions v "
        "JOIN definition_owners o ON o.kind = v.kind AND o.key = v.key "
        "WHERE v.kind = %s AND o.owner_kind = 'org' AND o.owner_id = %s ORDER BY v.key, v.version DESC",
        (kind, org_id),
    ).fetchall()
    return [_version(r) for r in rows]


def team_keys(conn, org_id: str) -> set[tuple[str, str]]:
    """(kind, key) of every definition the org owns."""
    rows = conn.execute(
        "SELECT kind, key FROM definition_owners WHERE owner_kind = 'org' AND owner_id = %s", (org_id,)
    ).fetchall()
    return {(r["kind"], r["key"]) for r in rows}


def org_owned_keys(conn) -> set[tuple[str, str]]:
    """(kind, key) of every definition any org owns: what teams built in their Studio."""
    rows = conn.execute("SELECT kind, key FROM definition_owners WHERE owner_kind = 'org'").fetchall()
    return {(r["kind"], r["key"]) for r in rows}


def hidden_from(conn, refs: list[tuple[str, str]], org_id: str) -> list[tuple[str, str]]:
    """The (kind, key) pairs of `refs` that `org_id` may not see, sorted."""
    if not refs:
        return []
    rows = conn.execute(
        "SELECT o.kind, o.key FROM definition_owners o "
        "JOIN unnest(%(kinds)s::text[], %(keys)s::text[]) AS r(kind, key) "
        "ON o.kind = r.kind AND o.key = r.key "
        "WHERE o.visibility = 'private' AND (o.owner_kind <> 'org' OR o.owner_id IS DISTINCT FROM %(org)s) "
        "ORDER BY o.kind, o.key",
        {"kinds": [kind for kind, _ in refs], "keys": [key for _, key in refs], "org": org_id},
    ).fetchall()
    return [(r["kind"], r["key"]) for r in rows]
