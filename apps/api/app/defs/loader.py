"""Read a definitions folder into a Bundle; parse single definitions from text (console edits)."""

import json
from pathlib import Path

import yaml

from app.defs import owners
from app.defs.model import SHARED_SCHEMAS, Bundle, Definition


class LoadError(ValueError):
    """A definition file could not be parsed at all (bad YAML/JSON, not a mapping, no kind/key), or names a
    key the files may not hold (one with "--", reserved for a workspace's own definitions)."""


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n")


def _read(path: Path) -> str:
    return _norm(path.read_bytes().decode("utf-8"))


def parse_definition(kind: str, key: str, text: str, files: dict[str, str], path: str) -> Definition:
    """Parse YAML (JSON for kind `schema`) `text`; `kind`/`key` are stripped from the body if present."""
    try:
        data = json.loads(text) if kind == "schema" else yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise LoadError(f"{path}: cannot parse: {exc}") from exc
    if not isinstance(data, dict):
        raise LoadError(f"{path}: top level must be a mapping")
    if kind == "schema":
        body = data
    else:
        if data.get("kind", kind) != kind or data.get("key", key) != key:
            raise LoadError(f"{path}: kind/key in file do not match {kind}/{key}")
        body = {k: v for k, v in data.items() if k not in ("kind", "key")}
    return Definition(kind=kind, key=key, body=body, files=dict(files), path=path)


def _from_file(kind: str, path: Path, root: Path, files: dict[str, str] | None = None) -> Definition:
    rel = path.relative_to(root).as_posix()
    text = _read(path)
    if kind == "schema":
        # packs/<slug>/schemas/<stem>.json is <slug>/<stem>; schemas/<stem>.json is shared/<stem>
        key = f"{path.parent.parent.name if rel.startswith('packs/') else SHARED_SCHEMAS}/{path.stem}"
    else:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise LoadError(f"{rel}: cannot parse: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
            raise LoadError(f"{rel}: expected a mapping with top-level `kind` and `key`")
        if raw.get("kind") != kind:
            raise LoadError(f"{rel}: expected kind {kind!r}, found {raw.get('kind')!r}")
        key = raw["key"]
    return parse_definition(kind, key, text, files or {}, rel)


def _agent_files(agent_yaml: Path) -> dict[str, str]:
    """Markdown named by runtime.instructions / runtime.skills, keyed by path relative to the agent folder.

    Missing or out-of-folder paths are skipped here; validation reports them.
    """
    try:
        runtime = (yaml.safe_load(_read(agent_yaml)) or {}).get("runtime") or {}
    except yaml.YAMLError, AttributeError:
        return {}
    names = [runtime.get("instructions"), *(runtime.get("skills") or [])]
    base = agent_yaml.parent.resolve()
    files: dict[str, str] = {}
    for name in names:
        if not isinstance(name, str):
            continue
        target = (base / name).resolve()
        if target.is_file() and target.is_relative_to(base):
            files[name] = _read(target)
    return files


def load_bundle(root: Path) -> Bundle:
    root = Path(root)
    found: list[Definition] = []
    for name, kind in (("taxonomy.yaml", "taxonomy"), ("models.yaml", "models")):
        if (root / name).is_file():
            found.append(_from_file(kind, root / name, root))
    for kind in ("pack", "workflow", "contract"):
        for p in sorted(root.glob(f"packs/*/{kind}.yaml")):
            found.append(_from_file(kind, p, root))
    for p in [*sorted(root.glob("packs/*/schemas/*.json")), *sorted(root.glob("schemas/*.json"))]:
        found.append(_from_file("schema", p, root))
    for p in sorted(root.glob("agents/*/agent.yaml")):
        found.append(_from_file("agent", p, root, _agent_files(p)))
    for kind, pattern in (
        ("connector", "connectors/*.yaml"),
        ("decision_rules", "decisions/*.yaml"),
        ("memory_space", "memory/*.yaml"),
    ):
        for p in sorted(root.glob(pattern)):
            found.append(_from_file(kind, p, root))
    items: dict[tuple[str, str], Definition] = {}
    for d in found:
        if owners.is_reserved(d.key):
            raise LoadError(
                f"{d.path}: key {d.key!r} contains {owners.SEPARATOR}, which belongs to a workspace's own "
                "definitions and never comes from the files"
            )
        if (d.kind, d.key) in items:
            raise LoadError(f"duplicate definition {d.kind}/{d.key} ({d.path})")
        items[(d.kind, d.key)] = d
    return Bundle(items=items)
