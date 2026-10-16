"""Imports the actions of one Composio toolkit into definitions/connectors/<toolkit>.yaml, so Studio's app
step offers them without each one being written by hand. Only schema lookups: no tool runs, and Composio meta
tools are never asked for.

Every action is sorted into read (runs freely), write (asks before it runs) or delete / money (blocked, so not
imported). The importer guesses from Composio's hints and the action's name; a person reviews the proposal and
writes any correction into scripts/connector_imports/<toolkit>.yaml, which wins over the guesses on every run.
That file can also name the capability prefix (`capability_prefix: sheets`), limit the import to actions
Composio tags (`only_tagged: important`) plus listed slugs (`include: [...]`), and block every unreviewed
write as money (`writes_are_money: true`, for payment apps), and name tools after Composio's slugs rather
than its display names (`ids_from: slug`). Per action, `drop` removes optional arguments and `restrict`
narrows one (`restrict: {status: {enum: [confirmed]}}`, with `items` stepping into an array) when an
argument could otherwise delete, share or sign in. Tools already in the connector file are kept exactly as
they are.

From apps/api:
    uv run --env-file ../../.env python scripts/import_connector.py googlesheets          # proposal only
    uv run --env-file ../../.env python scripts/import_connector.py googlesheets --apply  # write the files

--apply appends the new tools to the connector file, records their Composio schemas in tests/fixtures/composio
(as scripts/composio_schemas.py does) and writes a generated sandbox response for each one. Anything left out
on purpose because it is dangerous is skipped in the reviewed config, or listed in ALSO_NEVER_IMPORTED in
tests/test_defs_content.py."""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

API_ROOT = Path(__file__).parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from composio_schemas import OUT as FIXTURES  # noqa: E402
from composio_schemas import UncheckedSchema, structural  # noqa: E402

from app import settings, tool_words  # noqa: E402
from app.runtime.drivers import META_TOOL_PREFIX  # noqa: E402

OVERRIDES = Path(__file__).parent / "connector_imports"
CLASSES = ("read", "write", "delete", "money")
BLOCKED = {"delete", "money"}  # a pack can never use these, so they are not imported
# Shared with the sorting of an org's own MCP tools (app/tool_words.py); tests read them through this script.
READ_VERBS, WRITE_WORDS, DELETE_WORDS = tool_words.READ_VERBS, tool_words.WRITE_WORDS, tool_words.DELETE_WORDS
MONEY_WORDS, ACCESS_WORDS = tool_words.MONEY_WORDS, tool_words.ACCESS_WORDS
example = tool_words.example
WRITE_HINTS = {"updateHint", "createHint"}
# Composio's own keys that only describe a value; any other key Composio sends is a constraint we keep or,
# when the contract test cannot check it, a reason to leave the action out.
ANNOTATIONS = {
    "description",
    "title",
    "examples",
    "default",
    "$comment",
    "nullable",
    "format",
    "human_parameter_name",
    "human_parameter_description",
    "file_uploadable",
    "deprecated",
    "readOnly",
    "writeOnly",
}
DROPPED_WORDS = {"a", "an", "the"}
DESCRIPTION_LIMIT = 240
FETCH_LIMIT = 1000
# Our copy of Composio's schema keeps the keys the contract test checks, plus descriptions for Studio's form.
SCHEMA_KEYS = {
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
    "description",
}


@dataclass(frozen=True)
class Plan:
    """What the importer does with one Composio action."""

    slug: str
    tool_id: str
    action_class: str  # read | write | delete | money | skip | kept
    why: str
    entry: dict | None = None  # the connector tool entry, when the action is imported


def words(slug: str, toolkit: str) -> list[str]:
    """The slug's words after the toolkit prefix (SHEETS_LOOKUP_ROW -> LOOKUP, ROW)."""
    rest = slug.upper().removeprefix(toolkit.upper() + "_")
    return [w for w in rest.split("_") if w]


def classify(tool: dict, toolkit: str, override: dict | None) -> tuple[str, str]:
    """(action class or "skip", why) for one Composio action; a reviewed override wins. Delete and money
    words are checked before Composio's read-only hint: a name that deletes or moves money is blocked unless
    it plainly reads (starts with a read verb, with no write or money verb in it) or a person says
    otherwise."""
    if override and override.get("action_class"):
        return str(override["action_class"]), str(override.get("why") or "reviewed")
    if override and override.get("skip"):
        return "skip", str(override["skip"])
    tags = set(tool.get("tags") or [])
    found = words(tool["slug"], toolkit)
    named = set(found)
    if tool.get("is_deprecated"):
        return "skip", "deprecated in Composio"
    if "mcpIgnore" in tags:
        return "skip", "Composio keeps it out of agent tool lists"
    if "graphql" in {t.lower() for t in tags}:
        return "skip", "runs a free-form GraphQL document, so what it does cannot be known"
    if tags & {"destructiveHint", "destructive"}:
        return "delete", "marked destructive"
    if DELETE_WORDS & named:
        return "delete", "name deletes or cancels"
    reads = tool_words.plainly_reads(found) and not WRITE_HINTS & tags
    if reads:
        return "read", f"name starts with {found[0].lower()}"
    if ACCESS_WORDS & named or "SEND_AS" in tool["slug"]:
        return "skip", "is about who can reach data; needs a reviewed override"
    if MONEY_WORDS & named:
        return "money", "name moves money"
    if "readOnlyHint" in tags and not WRITE_WORDS & named and not WRITE_HINTS & tags:
        return "read", "marked read-only"
    if WRITE_HINTS & tags:
        return "write", "marked as creating or updating"
    return "write", "name changes data" if WRITE_WORDS & named else "changes data"


def tool_id(name: str, slug: str, toolkit: str, taken: set[str], app: str = "") -> str:
    """A short id from Composio's display name, unique in `taken`, without parentheses or a trailing
    "in <app>" ("Create Chart in Google Sheets" -> create_chart, "Create a Google Sheet" ->
    create_google_sheet)."""
    text = re.sub(r"\([^)]*\)", " ", name.lower())
    if app:
        stem = re.escape(app.lower().rstrip("s"))
        text = re.sub(rf"\s+(in|from|to|on)\s+{stem}s?\s*$", "", text.strip())
    parts = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in DROPPED_WORDS]
    base = "_".join(parts) or "_".join(words(slug, toolkit)).lower() or "tool"
    if not base[0].isalpha():
        base = f"tool_{base}"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def describe(text: str, fallback: str) -> str:
    """Composio's description on one line, cut at a sentence end within DESCRIPTION_LIMIT characters."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= DESCRIPTION_LIMIT:
        return flat or fallback
    cut = flat[:DESCRIPTION_LIMIT]
    end = max(cut.rfind(". "), cut.rfind("; "))
    return cut[: end + 1] if end > 40 else cut.rstrip() + "..."


def copy_schema(schema):
    """Composio's input schema with only SCHEMA_KEYS (and `format`) at every depth, property names kept as
    they are. An object that lists its properties and says nothing of others refuses them, at every depth."""
    if isinstance(schema, list):
        return [copy_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    kept = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            kept[key] = {name: copy_schema(sub) for name, sub in value.items()}
        elif key == "description":
            kept[key] = " ".join(str(value).split())
        elif key in SCHEMA_KEYS or key == "format":
            kept[key] = copy_schema(value)
    if isinstance(kept.get("properties"), dict) and "additionalProperties" not in kept:
        kept["additionalProperties"] = False
    return kept


def unknown_keys(schema, at: str) -> list[str]:
    """Where Composio's schema uses a key that is neither kept nor a mere annotation: a constraint the
    contract test would not see."""
    if isinstance(schema, list):
        return [p for i, s in enumerate(schema) for p in unknown_keys(s, f"{at}|{i}")]
    if not isinstance(schema, dict):
        return []
    found = [f"{at} uses {k}" for k in sorted(set(schema) - SCHEMA_KEYS - ANNOTATIONS)]
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            found += [p for name, sub in value.items() for p in unknown_keys(sub, f"{at}.{name}")]
        elif key in ("items", "anyOf", "additionalProperties"):
            found += unknown_keys(value, f"{at}[]" if key == "items" else at)
    return found


def narrowed(schema: dict, override: dict, slug: str) -> dict:
    """`schema` with a reviewed override's `drop` (optional top-level arguments removed) and `restrict`
    (schema keys set at a dotted path, where `items` steps into an array) applied."""
    out = json.loads(json.dumps(schema))
    for name in override.get("drop") or []:
        if name in (out.get("required") or []):
            raise ValueError(f"{slug}: cannot drop {name!r}, Composio requires it")
        if (out.get("properties") or {}).pop(name, None) is None:
            raise ValueError(f"{slug}: has no argument {name!r} to drop")
    for path, keys in (override.get("restrict") or {}).items():
        node = out
        for step in path.split("."):
            node = node.get("items") if step == "items" else (node.get("properties") or {}).get(step)
            if not isinstance(node, dict):
                raise ValueError(f"{slug}: has no argument at {path!r} to restrict")
        node.update(keys)
    return out


def input_schema(tool: dict, override: dict | None = None) -> dict:
    """Our input schema for an action: Composio's, refusing undeclared arguments at every depth and narrowed
    by a reviewed override. Raises UncheckedSchema when Composio's uses a constraint the contract test cannot
    check."""
    theirs = tool.get("input_parameters") or {"type": "object", "properties": {}}
    structural(theirs, tool["slug"])  # raises on what the contract test could not check
    if unknown := unknown_keys(theirs, tool["slug"]):
        raise UncheckedSchema(f"{unknown[0]}, which the contract test cannot check")
    ours = copy_schema(theirs)
    ours.pop("description", None)
    return narrowed({"type": "object", **ours, "additionalProperties": False}, override or {}, tool["slug"])


def sandbox_response(tool: dict) -> dict:
    """What simulated runs return for an action: an example of the `data` part of Composio's output."""
    out = tool.get("output_parameters") or {}
    data = (out.get("properties") or {}).get("data")
    value = example(data, out.get("$defs") or {}) if data else None
    return value if isinstance(value, dict) else {"result": value}


def wanted(tool: dict, config: dict) -> bool:
    """Whether the import considers an action: every one, or only those carrying `only_tagged` or listed in
    `include` (an action with a reviewed override is always considered)."""
    tag = config.get("only_tagged")
    slug = tool["slug"]
    if not tag or slug in (config.get("include") or []) or slug in (config.get("tools") or {}):
        return True
    return tag in (tool.get("tags") or [])


def plan(
    toolkit: str, tools: list[dict], existing: list[dict], config: dict, prefix: str, app: str = ""
) -> list[Plan]:
    """What to do with each Composio action, in slug order. `config` is the reviewed overrides file;
    `prefix` starts each capability (sheets.read); `app` is the connector's app name, left out of ids."""
    overrides = config.get("tools") or {}
    kept_slugs = {str(t["slug"]): str(t["id"]) for t in existing}
    taken = set(kept_slugs.values())
    # Reviewed ids are kept for their own actions, so an earlier action's generated id never takes one.
    reserved = {str(o["id"]): slug for slug, o in overrides.items() if isinstance(o, dict) and o.get("id")}
    plans = []
    for tool in sorted(tools, key=lambda t: t["slug"]):
        slug = tool["slug"]
        if slug.upper().startswith(META_TOOL_PREFIX) or not wanted(tool, config):
            continue
        if slug in kept_slugs:
            plans.append(Plan(slug, kept_slugs[slug], "kept", "already in the connector file"))
            continue
        override = overrides.get(slug) or {}
        action_class, why = classify(tool, toolkit, override)
        if action_class == "write" and not override.get("action_class") and config.get("writes_are_money"):
            action_class, why = "money", "every write in this app is blocked unless reviewed"
        if action_class not in (*CLASSES, "skip"):
            raise ValueError(f"{slug}: action_class must be one of {CLASSES}, not {action_class!r}")
        name = "" if config.get("ids_from") == "slug" else str(tool.get("name") or "")
        tid = str(override.get("id") or tool_id(name, slug, toolkit, taken | set(reserved), app))
        if tid in taken or reserved.get(tid, slug) != slug:
            raise ValueError(f"{slug}: id {tid!r} is already used")
        if action_class == "skip" or action_class in BLOCKED:
            plans.append(Plan(slug, tid, action_class, why))
            continue
        try:
            schema = input_schema(tool, override)
        except UncheckedSchema as exc:
            plans.append(Plan(slug, tid, "skip", str(exc)))
            continue
        description = override.get("description") or tool.get("description")
        if mentioned := [
            d for d in override.get("drop") or [] if re.search(rf"\b{re.escape(d)}\b", description or "")
        ]:
            raise ValueError(
                f"{slug}: the description still offers {mentioned}; give it a reviewed description"
            )
        taken.add(tid)
        entry = {
            "id": tid,
            "slug": slug,
            "version": str(tool["version"]),
            "action_class": action_class,
            "capability": str(override.get("capability") or f"{prefix}.{action_class}"),
            "description": describe(description, tid),
            "input_schema": schema,
        }
        plans.append(Plan(slug, tid, action_class, why, entry))
    return plans


def with_tools(text: str, entries: list[dict], toolkit: str) -> str:
    """The connector file's text with `entries` added after its last tool; the rest is left as it is."""
    at = text.find("\ndefaults:")
    if at < 0:
        raise ValueError("the connector file has no top-level defaults: line to add the tools before")
    dumped = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=110)
    block = "".join(f"  {line}\n" if line else "\n" for line in dumped.splitlines())
    note = (
        f"\n  # Imported from Composio by scripts/import_connector.py {toolkit}; reviewed choices are in"
        f"\n  # scripts/connector_imports/{toolkit}.yaml.\n"
    )
    return text[:at].rstrip("\n") + "\n" + note + block + text[at:]


def report(plans: list[Plan]) -> str:
    """The proposal as a table."""
    lines = ["| Action | id | Class | Why |", "|---|---|---|---|"]
    order = {"kept": 0, "read": 1, "write": 2, "money": 3, "delete": 4, "skip": 5}
    for p in sorted(plans, key=lambda p: (order[p.action_class], p.slug)):
        imported = "imported" if p.entry else "not imported" if p.action_class in BLOCKED | {"skip"} else ""
        lines.append(f"| {p.slug} | {p.tool_id} | {p.action_class} {imported} | {p.why} |")
    lines += ["", f"{sum(1 for p in plans if p.entry)} to import."]
    return "\n".join(lines)


def write_files(toolkit: str, connector_path: Path, plans: list[Plan], tools: dict[str, dict]) -> None:
    added = [p.entry for p in plans if p.entry]
    if not added:
        return
    text = connector_path.read_text(encoding="utf-8")
    before = yaml.safe_load(text).get("tools") or []
    updated = with_tools(text, added, toolkit)
    after = yaml.safe_load(updated).get("tools") or []
    if after[: len(before)] != before or after[len(before) :] != added:
        raise RuntimeError(f"{connector_path.name}: the tools did not land at the end of the tools list")
    connector_path.write_bytes(updated.encode("utf-8"))
    sandbox = settings.defs_dir() / "connectors" / "sandbox" / toolkit
    sandbox.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for entry in added:
        tool = tools[entry["slug"]]
        record = {
            "slug": entry["slug"],
            "version": entry["version"],
            "input_parameters": structural(tool.get("input_parameters") or {}, entry["slug"]),
        }
        recorded = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (FIXTURES / f"{entry['slug']}.json").write_bytes(recorded.encode("utf-8"))
        response = json.dumps(sandbox_response(tool), indent=2, ensure_ascii=False) + "\n"
        (sandbox / f"{entry['id']}.json").write_bytes(response.encode("utf-8"))
        print(f"Added {toolkit}.{entry['id']} ({entry['slug']} {entry['version']})")


def fetch(toolkit: str) -> list[dict]:
    """Every action of the toolkit, as plain dicts, at the toolkit's current version."""
    from composio import Composio  # reads COMPOSIO_API_KEY from the environment

    client = Composio(allow_tracking=False)  # no SDK telemetry
    raw = client.tools.get_raw_composio_tools(toolkits=[toolkit], limit=FETCH_LIMIT)
    found = [t.model_dump() for t in raw]
    if len(found) >= FETCH_LIMIT:
        print(f"Warning: Composio returned {len(found)} actions, the most asked for; some may be missing.")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("toolkit", help="the Composio toolkit slug, such as googlesheets")
    parser.add_argument("--apply", action="store_true", help="write the files; without it, only report")
    args = parser.parse_args()
    toolkit = args.toolkit.lower()
    connector_path = settings.defs_dir() / "connectors" / f"{toolkit}.yaml"
    if not connector_path.is_file():
        sys.exit(f"{connector_path} does not exist: write its app, toolkit and defaults first")
    body = yaml.safe_load(connector_path.read_text(encoding="utf-8"))
    existing = body.get("tools") or []
    config_path = OVERRIDES / f"{toolkit}.yaml"
    config = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}) if config_path.is_file() else {}
    first = str(existing[0]["capability"]).split(".")[0] if existing else toolkit
    prefix = str(config.get("capability_prefix") or first)
    tools = fetch(toolkit)
    plans = plan(toolkit, tools, existing, config, prefix, str(body.get("app") or ""))
    print(report(plans))
    if args.apply:
        write_files(toolkit, connector_path, plans, {t["slug"]: t for t in tools})


if __name__ == "__main__":
    main()
