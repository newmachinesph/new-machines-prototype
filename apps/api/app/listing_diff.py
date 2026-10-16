"""The definition diff ops reviews (sub-project D): the files of a submitted version's bundle against the
listing's approved bundle, as unified diffs."""

import difflib

from app.defs import registry
from app.models.publishing import DefinitionDiff


def _files(conn, bundle: list[dict] | None) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    for d in bundle or []:
        v = registry.get_version(conn, d["kind"], d["key"], int(d["version"]))
        out[(d["kind"], d["key"])] = registry.export_files(v) if v else {}
    return out


def diff(conn, before: list[dict] | None, after: list[dict]) -> list[DefinitionDiff]:
    """Per definition in either bundle (by kind, key, path), one entry per changed file with a unified diff;
    nothing for unchanged files. `before=None` compares with nothing: every file is added."""
    old, new = _files(conn, before), _files(conn, after)
    changes: list[DefinitionDiff] = []
    for kind, key in sorted(set(old) | set(new)):
        a, b = old.get((kind, key), {}), new.get((kind, key), {})
        for path in sorted(set(a) | set(b)):
            if a.get(path) == b.get(path):
                continue
            change = "added" if path not in a else "removed" if path not in b else "changed"
            unified = "".join(
                difflib.unified_diff(
                    (a.get(path) or "").splitlines(keepends=True),
                    (b.get(path) or "").splitlines(keepends=True),
                    fromfile=f"approved/{path}",
                    tofile=f"submitted/{path}",
                )
            )
            changes.append(DefinitionDiff(kind=kind, key=key, path=path, change=change, unified=unified))
    return changes
