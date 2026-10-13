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
def _file_bodies(root: Path) -> dict[tuple[str, str], dict]:
    try:
        bundle = load_bundle(root)
    except LoadError, OSError:
        log.warning("Definition files in %s could not be read; serving none.", root, exc_info=True)
        return {}
    return {key: d.body for key, d in bundle.items.items()}


def latest_bodies(kind: str) -> dict[str, dict]:
    """{key: body} of the latest version of every definition of `kind`."""
    if settings.runtime_enabled():
        with db.connect() as conn:
            return {v.key: v.body for v in registry.latest_all(conn) if v.kind == kind}
    return {key: body for (k, key), body in _file_bodies(settings.defs_dir()).items() if k == kind}
