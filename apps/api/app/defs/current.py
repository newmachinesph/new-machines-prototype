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


def latest_with_files(kind: str) -> dict[str, tuple[dict, dict[str, str]]]:
    """{key: (body, files)} of the latest version of every definition of `kind`; `files` holds an agent's
    Markdown by path relative to its folder (empty for other kinds)."""
    if settings.runtime_enabled():
        with db.connect() as conn:
            return {v.key: (v.body, v.files) for v in registry.latest_all(conn) if v.kind == kind}
    return {key: item for (k, key), item in _file_items(settings.defs_dir()).items() if k == kind}


def latest_bodies(kind: str) -> dict[str, dict]:
    """{key: body} of the latest version of every definition of `kind`."""
    return {key: body for key, (body, _) in latest_with_files(kind).items()}
