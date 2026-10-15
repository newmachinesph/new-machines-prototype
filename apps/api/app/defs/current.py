"""The latest definition bodies for read-only API views (catalog taxonomy, pack metadata, memory spaces).

With the runtime on they come from the Postgres registry, so a console publish shows up at once. With it
off (the static demo, the default test suite) they come from the definition files, read once per process.
"""

import logging
from functools import cache
from pathlib import Path

from app import db, settings
from app.defs import registry
from app.defs.loader import LoadError, load_bundle

log = logging.getLogger(__name__)


@cache
def _file_items(root: Path) -> dict[tuple[str, str], tuple[dict, dict[str, str]]]:
    try:
        bundle = load_bundle(root)
    except LoadError, OSError:
        log.warning("Definition files in %s could not be read; serving none.", root, exc_info=True)
        return {}
    return {key: (d.body, d.files) for key, d in bundle.items.items()}


def latest_with_files(kind: str, org_id: str | None = None) -> dict[str, tuple[dict, dict[str, str]]]:
    """{key: (body, files)} of the latest version of every definition of `kind` that `org_id` may see (None:
    the platform's and marketplace ones only). `files` holds an agent's Markdown by path relative to its
    folder (empty for other kinds). The definition files never hold an org's own definitions."""
    if settings.runtime_enabled():
        with db.connect() as conn:
            return {v.key: (v.body, v.files) for v in registry.latest_visible(conn, org_id) if v.kind == kind}
    return {key: item for (k, key), item in _file_items(settings.defs_dir()).items() if k == kind}


def latest_bodies(kind: str, org_id: str | None = None) -> dict[str, dict]:
    """{key: body} of the latest version of every definition of `kind` that `org_id` may see."""
    return {key: body for key, (body, _) in latest_with_files(kind, org_id).items()}


def team_keys(org_id: str | None) -> set[tuple[str, str]]:
    """(kind, key) of the org's own definitions; none without an org or with the runtime off."""
    if org_id is None or not settings.runtime_enabled():
        return set()
    with db.connect() as conn:
        return registry.team_keys(conn, org_id)
