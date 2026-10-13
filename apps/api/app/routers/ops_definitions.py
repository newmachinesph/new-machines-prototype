"""Operator console: browse, validate, publish and export versioned definitions ("config as code").

Everything reads the Postgres registry, so these endpoints answer 503 RUNTIME_UNAVAILABLE while the
runtime is off. Publishing validates the edited definition against the latest published versions of
everything else, inserts the next version (source "console") and writes an ops audit entry.
"""

import json
import re
from pathlib import PurePosixPath
from typing import Annotated

import yaml
from fastapi import Query

from app import db
from app.auth import CurrentOps, OpsWriter
from app.defs import refs, registry
from app.defs.model import Bundle, Definition, path_for
from app.defs.validate import validate_bundle
from app.errors import ApiProblem, ProblemIssue
from app.models.ops import (
    DefinitionDetail,
    DefinitionExport,
    DefinitionIssue,
    DefinitionKind,
    DefinitionRef,
    DefinitionSummary,
    PublishDefinitionRequest,
    ValidateDefinitionRequest,
    ValidateDefinitionResult,
    VersionMeta,
)
from app.routers.ops_params import PathId
from app.routers.ops_runtime import RUNTIME_RESPONSES, require_runtime
from app.routing import ApiRouter
from app.store import locked_store

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

# `{key:path}` so a schema's key (`<pack slug>/<file stem>`) fits in the URL.
KEY = "{key:path}"

VersionQuery = Annotated[int | None, Query(ge=1, description="An older version; the latest when omitted.")]


def display_name(v: registry.Version) -> str:
    """The body's name, else the connector's app, else the decision rules' question, else the key."""
    for field in ("name", "app", "question"):
        if isinstance(v.body.get(field), str) and v.body[field]:
            return v.body[field]
    return v.key


def summary_of(v: registry.Version) -> DefinitionSummary:
    return DefinitionSummary(
        kind=v.kind,
        key=v.key,
        name=display_name(v),
        version=v.version,
        digest=v.digest,
        source=v.source,
        published_by=v.published_by,
        published_at=v.published_at,
    )


def _refs(pairs: list[tuple[str, str]]) -> list[DefinitionRef]:
    return [DefinitionRef(kind=k, key=key) for k, key in pairs]


def detail_of(conn, kind: str, key: str, version: int | None = None) -> DefinitionDetail:
    history = registry.versions(conn, kind, key)
    if not history:
        raise ApiProblem(404, "NOT_FOUND", f"No definition {kind}/{key}.")
    chosen = history[0] if version is None else next((v for v in history if v.version == version), None)
    if chosen is None:
        raise ApiProblem(404, "NOT_FOUND", f"{kind}/{key} has no version {version}.")
    bundle = registry.latest_bundle(conn)
    return DefinitionDetail(
        summary=summary_of(chosen),
        versions=[
            VersionMeta(
                version=v.version,
                digest=v.digest,
                source=v.source,
                published_by=v.published_by,
                reason=v.reason,
                published_at=v.published_at,
            )
            for v in history
        ],
        yaml=registry.export_files(chosen)[path_for(kind, key)],
        body=chosen.body,
        files=chosen.files,
        refs=_refs(refs.refs_in(bundle, kind, key)),
        used_by=_refs(refs.used_by(bundle, kind, key)),
    )


def _issue(kind: str, key: str, path: str, message: str) -> DefinitionIssue:
    return DefinitionIssue(kind=kind, key=key, path=path, message=message)


KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")  # a new definition's key (a schema's has one slash)


class _Unparseable(Exception):
    """The submitted text cannot be read; the message is safe to show to the user."""


def _has_anchor(text: str) -> bool:
    """True when the YAML uses an anchor or alias, which can expand into a huge structure."""
    return any(
        isinstance(e, yaml.AliasEvent) or getattr(e, "anchor", None) is not None for e in yaml.parse(text)
    )


def _parse_text(kind: str, text: str) -> dict:
    """The submitted main file as a mapping. Raises _Unparseable with a user-facing message."""
    try:
        if kind == "schema":
            data = json.loads(text)
        elif _has_anchor(text):
            raise _Unparseable("YAML anchors and aliases (& and *) are not allowed.")
        else:
            data = yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        raise _Unparseable(f"JSON is not valid: line {exc.lineno}, column {exc.colno}: {exc.msg}.") from None
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        problem = (exc.problem or "cannot be read").replace("<stream end>", "the end of the text")
        raise _Unparseable(f"YAML is not valid: {where}{problem}.") from None
    except yaml.YAMLError:
        raise _Unparseable("YAML is not valid.") from None
    if not isinstance(data, dict):
        raise _Unparseable("The top level must be a mapping.")
    return data


def _definition(kind: str, key: str, data: dict, files: dict[str, str]) -> Definition:
    """422 KEY_MISMATCH when the text names a different kind or key than the URL (schemas name neither)."""
    if kind == "schema":
        body = data
    else:
        if data.get("kind", kind) != kind or data.get("key", key) != key:
            raise ApiProblem(
                422,
                "KEY_MISMATCH",
                f"The YAML says {data.get('kind', kind)}/{data.get('key', key)} but the URL is {kind}/{key}.",
            )
        body = {k: v for k, v in data.items() if k not in ("kind", "key")}
    return Definition(kind=kind, key=key, body=body, files=dict(files), path=path_for(kind, key))


def _check_new_key(kind: str, key: str) -> None:
    parts = key.split("/") if kind == "schema" else [key]
    if len(parts) > (2 if kind == "schema" else 1) or not all(KEY_PATTERN.fullmatch(p) for p in parts):
        raise ApiProblem(
            422,
            "INVALID_KEY",
            "A new key is lowercase letters, digits, - and _ (a schema's is <pack>/<name>).",
        )
    if kind == "schema" and len(parts) != 2:
        raise ApiProblem(422, "INVALID_KEY", "A schema's key is <pack slug>/<name>.")
    if kind in ("taxonomy", "models") and key != "default":
        raise ApiProblem(422, "INVALID_KEY", f"The key of {kind} is always default.")


def _file_issues(kind: str, key: str, files: dict[str, str]) -> list[DefinitionIssue]:
    if files and kind != "agent":
        return [_issue(kind, key, "files", "only agents have extra files")]
    issues = []
    for name in files:
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or "\\" in name or not name.strip():
            msg = "path must be relative and stay inside the folder"
            issues.append(_issue(kind, key, f"files[{name}]", msg))
    return issues


def check_edit(
    conn, kind: str, key: str, body: ValidateDefinitionRequest
) -> tuple[Definition | None, list[DefinitionIssue], bool]:
    """Parse the edit and validate it against the latest published versions of everything else. An unknown
    kind/key is a new definition. Returns (definition, errors, is_new); the definition is None when the text
    did not parse."""
    is_new = registry.latest(conn, kind, key) is None
    if is_new:
        _check_new_key(kind, key)
    issues = _file_issues(kind, key, body.files)
    try:
        data = _parse_text(kind, body.yaml)
    except _Unparseable as exc:
        return None, [*issues, _issue(kind, key, "(root)", str(exc))], is_new
    edited = _definition(kind, key, data, body.files)
    items = dict(registry.latest_bundle(conn).items)
    items[(kind, key)] = edited
    errors = [_issue(e.kind, e.key, e.path, e.message) for e in validate_bundle(Bundle(items=items))]
    return edited, [*issues, *errors], is_new


@router.get(
    "/definitions",
    operation_id="opsListDefinitions",
    response_model=list[DefinitionSummary],
    responses=RUNTIME_RESPONSES,
)
def ops_list_definitions(_: CurrentOps) -> list[DefinitionSummary]:
    """The latest version of every definition, by kind then key."""
    require_runtime()
    with db.connect() as conn:
        return [summary_of(v) for v in registry.latest_all(conn)]


@router.get(
    f"/definitions/{{kind}}/{KEY}/export",
    operation_id="opsExportDefinition",
    response_model=DefinitionExport,
    responses=RUNTIME_RESPONSES,
)
def ops_export_definition(
    kind: DefinitionKind, key: PathId, _: CurrentOps, version: VersionQuery = None
) -> DefinitionExport:
    """The files of one version as {path relative to the definitions root: text}, ready to go into git."""
    require_runtime()
    with db.connect() as conn:
        found = (
            registry.latest(conn, kind, key)
            if version is None
            else registry.get_version(conn, kind, key, version)
        )
    if found is None:
        suffix = f" v{version}." if version else "."
        raise ApiProblem(404, "NOT_FOUND", f"No definition {kind}/{key}{suffix}")
    return DefinitionExport(files=registry.export_files(found))


@router.post(
    f"/definitions/{{kind}}/{KEY}:validate",
    operation_id="opsValidateDefinition",
    response_model=ValidateDefinitionResult,
    responses=RUNTIME_RESPONSES,
)
def ops_validate_definition(
    kind: DefinitionKind, key: PathId, body: ValidateDefinitionRequest, _: CurrentOps
) -> ValidateDefinitionResult:
    """Check an edit (or a new definition) against the latest published versions of everything else. Never
    saves anything.
    `errors` lists every problem found, including ones in other definitions."""
    require_runtime()
    with db.connect() as conn:
        _, errors, _ = check_edit(conn, kind, key, body)
    return ValidateDefinitionResult(ok=not errors, errors=errors)


@router.post(
    f"/definitions/{{kind}}/{KEY}:publish",
    operation_id="opsPublishDefinition",
    response_model=DefinitionDetail,
    status_code=201,
    responses=RUNTIME_RESPONSES,
)
def ops_publish_definition(
    kind: DefinitionKind, key: PathId, body: PublishDefinitionRequest, actor: OpsWriter
) -> DefinitionDetail:
    """Validate, then publish the edit as the next version; an unknown kind/key is created as version 1.
    422 INVALID_DEFINITION (with `errors`) when it does not validate; 409 VERSION_CONFLICT when
    `baseVersion` is sent and someone has published since; 409 NO_CHANGE when it equals the latest
    version."""
    require_runtime()
    with db.connect() as conn:
        edited, errors, _ = check_edit(conn, kind, key, body)
        if edited is None or errors:
            first = errors[0]
            raise ApiProblem(
                422,
                "INVALID_DEFINITION",
                f"{len(errors)} problem(s); first: {first.kind}/{first.key} ({first.path}): {first.message}",
                [ProblemIssue(**e.model_dump()) for e in errors],
            )
        before = registry.latest(conn, kind, key)
        try:
            published = registry.publish(
                conn, edited, actor.email, body.reason, base_version=body.base_version
            )
        except registry.VersionConflict as conflict:
            raise ApiProblem(
                409,
                "VERSION_CONFLICT",
                f"v{conflict.latest} of {kind}/{key} was published since this edit started from "
                f"v{conflict.base}. Copy your changes, reload the latest version and apply them again.",
            ) from None
        except registry.NoChange:
            raise ApiProblem(409, "NO_CHANGE", f"{kind}/{key} is unchanged.") from None
        detail = detail_of(conn, kind, key)
        conn.commit()
    action = "definition.create" if before is None else "definition.publish"
    summary = (
        f"created v{published.version}" if before is None else f"v{before.version} → v{published.version}"
    )
    with locked_store() as store:
        store.audit(actor, action, "definition", f"{kind}/{key}", body.reason, summary)
    return detail


# Registered last: `{key:path}` would otherwise swallow the `/export` suffix.
@router.get(
    f"/definitions/{{kind}}/{KEY}",
    operation_id="opsGetDefinition",
    response_model=DefinitionDetail,
    responses=RUNTIME_RESPONSES,
)
def ops_get_definition(
    kind: DefinitionKind, key: PathId, _: CurrentOps, version: VersionQuery = None
) -> DefinitionDetail:
    """One definition with its version history, its main file as YAML, Markdown files, and what it refers
    to / is used by. `?version=N` shows an older version."""
    require_runtime()
    with db.connect() as conn:
        return detail_of(conn, kind, key, version)
