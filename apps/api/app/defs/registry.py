"""Postgres-backed, append-only version registry for definitions.

Every function runs on the caller's connection and never commits: the caller owns the transaction.
"""

import json
import logging
import secrets
from dataclasses import dataclass

import yaml
from psycopg.types.json import Jsonb

from app.defs.digest import digest
from app.defs.model import Bundle, Definition, path_for

_ADVISORY_LOCK = 7_204_100_001  # serialises concurrent version inserts
FILE, CONSOLE = "file", "console"  # definition_versions.source

log = logging.getLogger(__name__)


class NoChange(Exception):
    """The published definition is identical (same digest) to the latest version."""


class VersionConflict(Exception):
    """The latest version is not the one the edit started from: someone published in between."""

    def __init__(self, latest: int, base: int) -> None:
        super().__init__(f"latest is v{latest}, the edit started from v{base}")
        self.latest = latest
        self.base = base


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
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK,))
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
    for space in bundle.of("memory_space"):
        items = space.body.get("seed_items") or []
        if not items:
            continue
        if conn.execute("SELECT 1 FROM memory_items WHERE space = %s LIMIT 1", (space.key,)).fetchone():
            continue
        for text in items:
            conn.execute(
                "INSERT INTO memory_items (id, space, text, source, created_by) VALUES (%s, %s, %s, %s, %s)",
                (f"mem_{secrets.token_hex(6)}", space.key, text, "seed", actor),
            )


def apply_bundle(
    conn, bundle: Bundle, actor: str = "definitions-apply", *, force: bool = False
) -> list[Version]:
    """Insert a new version per definition whose digest differs from its latest; seed empty memory spaces.

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


def publish(conn, d: Definition, actor: str, reason: str, *, base_version: int | None = None) -> Version:
    """Publish a console edit as the next version (source='console'). Does not commit.

    Raises VersionConflict when `base_version` is given and is not the latest version, and NoChange when
    the digest equals the latest version's.
    """
    v = _insert(conn, d, CONSOLE, actor, reason, base_version=base_version)
    if v is None:
        raise NoChange(f"{d.kind}/{d.key} is unchanged")
    return v


def latest_bundle(conn) -> Bundle:
    items = {
        (v.kind, v.key): Definition(
            kind=v.kind, key=v.key, body=v.body, files=v.files, path=path_for(v.kind, v.key)
        )
        for v in latest_all(conn)
    }
    return Bundle(items=items)


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
