"""The latest definition bodies for read-only API views (catalog taxonomy, pack metadata, memory spaces).

With the runtime on they come from the Postgres registry, so a console publish shows up at once. With it
off (the static demo, the default test suite) they come from the definition files, read once per process:
`warm_in_background` reads them at startup, so the first request does not wait for the read.
"""

import logging
import threading
import time
from pathlib import Path

from app import db, settings
from app.defs import registry
from app.defs.loader import LoadError, load_bundle

log = logging.getLogger(__name__)

Items = dict[tuple[str, str], tuple[dict, dict[str, str]]]

# How long a failed read serves none before the files are read again: a folder that stays broken must not
# cost every request a full read under the lock.
FAILED_READ_HOLD_S = 30.0

# The definition files once read, by their folder. One read at a time: a request that arrives while the
# startup warm-up is reading waits for that read instead of starting its own.
_lock = threading.Lock()
_items: dict[Path, Items] = {}
_failed_at: dict[Path, float] = {}  # when a folder's last read failed (time.monotonic)


def _file_items(root: Path) -> Items:
    """{(kind, key): (body, files)} of the definition files under `root`, read on the first call. A read that
    fails is logged once and serves none for FAILED_READ_HOLD_S; then the next call reads again."""
    with _lock:
        items = _items.get(root)
        if items is not None:
            return items
        failed = _failed_at.get(root)
        if failed is not None and time.monotonic() - failed < FAILED_READ_HOLD_S:
            return {}
        try:
            bundle = load_bundle(root)
        except LoadError, OSError:
            _failed_at[root] = time.monotonic()
            log.warning(
                "Definition files in %s could not be read; serving none for the next %.0f s.",
                root,
                FAILED_READ_HOLD_S,
                exc_info=True,
            )
            return {}
        _failed_at.pop(root, None)
        items = _items[root] = {key: (d.body, d.files) for key, d in bundle.items.items()}
        return items


def warm() -> None:
    """Read the definition files now, so no request pays for the read. Nothing to do with the runtime on: the
    bodies then come from the registry."""
    if settings.runtime_enabled():
        return
    _file_items(settings.defs_dir())


def warm_in_background() -> threading.Thread | None:
    """`warm` on its own thread, so readiness does not wait for the read (about 3 s for the demo's files). A
    read that fails is logged there, never raised here. None with the runtime on, when there is nothing to
    read."""
    if settings.runtime_enabled():
        return None
    thread = threading.Thread(target=warm, name="definitions-warm-up", daemon=True)
    thread.start()
    return thread


def forget_files() -> None:
    """Drop what was read and any failure held, so the next call reads the files again (tests)."""
    with _lock:
        _items.clear()
        _failed_at.clear()


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
