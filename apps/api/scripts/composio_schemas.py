"""Records the Composio input schema of every connector tool slug in definitions/connectors, at the toolkit
version the tool pins, into tests/fixtures/composio/<SLUG>.json, which tests/test_composio_contract.py checks
the definitions against. Only schema lookups: no tool runs, and Composio meta tools are never asked for.
Needs COMPOSIO_API_KEY: `uv run --env-file ../../.env python scripts/composio_schemas.py` from apps/api.
Run it again after changing a connector tool's slug or pinned version."""

import json
import sys
from pathlib import Path

import yaml

API_ROOT = str(Path(__file__).parents[1])
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)

from app import settings  # noqa: E402
from app.runtime.drivers import META_TOOL_PREFIX  # noqa: E402

OUT = Path(__file__).parents[1] / "tests" / "fixtures" / "composio"
# The schema keys the contract test reads; descriptions, examples and titles change too often to record.
KEEP = {
    "type",
    "properties",
    "required",
    "enum",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "items",
    "anyOf",
    "additionalProperties",
}
# Keywords that constrain a value but that the contract test cannot check: recording one would hide it.
UNCHECKED = {"oneOf", "allOf", "$ref", "$defs", "const", "not"}


class UncheckedSchema(ValueError):
    """Composio's schema uses a keyword the contract test cannot check (UNCHECKED)."""


def tools() -> list[tuple[str, str, str | None]]:
    """(slug, toolkit, pinned version or None) for each connector tool slug, except Composio meta tools."""
    found: dict[str, tuple[str, str, str | None]] = {}
    for path in sorted((settings.defs_dir() / "connectors").glob("*.yaml")):
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
        for tool in body.get("tools") or []:
            slug = str(tool.get("slug") or "")
            if slug and not slug.upper().startswith(META_TOOL_PREFIX):
                version = str(tool["version"]) if tool.get("version") else None
                seen = found.setdefault(slug, (slug, str(body["toolkit"]), version))
                if seen[2] != version:
                    raise ValueError(f"{slug} is pinned at {seen[2]} and {version}; pin one version")
    return [found[slug] for slug in sorted(found)]


def structural(schema, at: str):
    """`schema` (found at `at`) with only the KEEP keys, at every depth; property names are kept as they are.
    Raises UncheckedSchema when a schema uses an UNCHECKED keyword."""
    if isinstance(schema, list):
        return [structural(s, f"{at}|{i}") for i, s in enumerate(schema)]
    if not isinstance(schema, dict):
        return schema
    if used := sorted(UNCHECKED & set(schema)):
        raise UncheckedSchema(f"{at} uses {', '.join(used)}, which the contract test cannot check")
    kept = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            kept[key] = {name: structural(sub, f"{at}.{name}") for name, sub in value.items()}
        elif key in KEEP:
            kept[key] = structural(
                value, {"items": f"{at}[]", "additionalProperties": f"{at}.*"}.get(key, at)
            )
    return kept


def main() -> None:
    from composio import Composio  # reads COMPOSIO_API_KEY from the environment
    from composio.exceptions import ToolNotFoundError

    clients: dict[tuple[str, str | None], object] = {}
    wanted, failed = tools(), []
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, toolkit, version in wanted:
        if (toolkit, version) not in clients:
            pin = {"toolkit_versions": {toolkit: version}} if version else {}
            clients[(toolkit, version)] = Composio(allow_tracking=False, **pin)  # no SDK telemetry
        try:
            tool = clients[(toolkit, version)].tools.get_raw_composio_tool_by_slug(slug)
        except ToolNotFoundError:
            failed.append(f"Composio has no tool {slug} ({toolkit} {version or 'latest'})")
            continue
        try:
            schema = structural(tool.input_parameters, slug)
        except UncheckedSchema as exc:
            failed.append(str(exc))
            continue
        record = {"slug": slug, "version": tool.version, "input_parameters": schema}
        text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (OUT / f"{slug}.json").write_bytes(text.encode("utf-8"))
        print(f"Wrote {slug} ({tool.version})")
    for stale in sorted(set(p.stem for p in OUT.glob("*.json")) - {slug for slug, _, _ in wanted}):
        (OUT / f"{stale}.json").unlink()
        print(f"Removed {stale} (no connector tool uses it)")
    if failed:
        for problem in failed:
            print(problem, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
