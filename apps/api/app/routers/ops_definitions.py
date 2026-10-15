"""Operator console: browse, validate, publish and export versioned definitions ("config as code").

Everything reads the Postgres registry, so these endpoints answer 503 RUNTIME_UNAVAILABLE while the
runtime is off. Publishing validates the edited definition against the latest published versions of
everything else, inserts the next version (source "console") and writes an ops audit entry.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Query

from app import db, ops_state, workspace
from app.auth import CurrentOps, OpsWriter
from app.defs import owners, refs, registry
from app.defs import text as def_text
from app.defs.model import Bundle, Definition, path_for
from app.defs.validate import validate_bundle
from app.errors import NO_CHANGE, ApiProblem, ProblemIssue, conflicts
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


def require_platform(conn, kind: str, key: str) -> None:
    """An org's or a developer's own definition is not shown or edited in the console: 404, as for an unknown
    key (`registry.latest_platform` lists by the same rule)."""
    if registry.owner_of(conn, kind, key).kind != "platform":
        raise ApiProblem(404, "NOT_FOUND", f"No definition {kind}/{key}.")


def detail_of(conn, kind: str, key: str, version: int | None = None) -> DefinitionDetail:
    require_platform(conn, kind, key)
    history = registry.versions(conn, kind, key)
    if not history:
        raise ApiProblem(404, "NOT_FOUND", f"No definition {kind}/{key}.")
    chosen = history[0] if version is None else next((v for v in history if v.version == version), None)
    if chosen is None:
        raise ApiProblem(404, "NOT_FOUND", f"{kind}/{key} has no version {version}.")
    bundle = registry.visible_bundle(conn, None)
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
    if owners.is_reserved(key):
        raise ApiProblem(422, "INVALID_KEY", "A key with -- belongs to a workspace's own definitions.")
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


def _team_breaks(conn, platform: Bundle, edited: Definition) -> int:
    """How many of the definitions teams built in their Studio (org-owned; the console never names them) stop
    validating with the edit. One that is already broken without it is not counted."""
    everything = registry.latest_bundle(conn)
    team = (set(everything.items) - set(platform.items)) & registry.org_owned_keys(conn)
    if not team:
        return 0
    with_edit = Bundle(items={**everything.items, (edited.kind, edited.key): edited})
    broken = {(e.kind, e.key) for e in validate_bundle(with_edit) if (e.kind, e.key) in team}
    if not broken:
        return 0
    already = {(e.kind, e.key) for e in validate_bundle(everything)}
    return len(broken - already)


def _team_warning(count: int) -> list[str] | None:
    """The warning for `count` broken team definitions: a count only, never a key, name or org."""
    if count == 0:
        return None
    noun = "definition a team built" if count == 1 else "definitions teams built"
    return [f"This edit breaks {count} {noun} in the Studio. Those teams will need to update their work."]


@dataclass(frozen=True)
class Edit:
    """A checked edit. `definition` is None when the text did not parse; `warnings` is for Validate and
    Publish, and never names a team's definition."""

    definition: Definition | None
    errors: list[DefinitionIssue]
    is_new: bool
    warnings: list[str] | None = None


def check_edit(conn, kind: str, key: str, body: ValidateDefinitionRequest) -> Edit:
    """Parse the edit and validate it against the latest published versions of every other platform
    definition. Platform definitions only: an org's or a developer's own key is 404, and a key with "--"
    cannot be created. An unknown kind/key is a new definition. The private definitions orgs built are
    validated too, but only counted: see `_team_breaks`."""
    require_platform(conn, kind, key)
    is_new = registry.latest(conn, kind, key) is None
    if is_new:
        _check_new_key(kind, key)
    issues = _file_issues(kind, key, body.files)
    try:
        data = def_text.parse_text(kind, body.yaml)
    except def_text.Unparseable as exc:
        return Edit(None, [*issues, _issue(kind, key, "(root)", str(exc))], is_new)
    edited = _definition(kind, key, data, body.files)
    platform = registry.visible_bundle(conn, None)
    items = {**platform.items, (kind, key): edited}
    errors = [_issue(e.kind, e.key, e.path, e.message) for e in validate_bundle(Bundle(items=items))]
    warnings = _team_warning(_team_breaks(conn, platform, edited)) if not errors else None
    return Edit(edited, [*issues, *errors], is_new, warnings)


@router.get(
    "/definitions",
    operation_id="opsListDefinitions",
    response_model=list[DefinitionSummary],
    responses=RUNTIME_RESPONSES,
)
def ops_list_definitions(_: CurrentOps) -> list[DefinitionSummary]:
    """The latest version of every platform definition, by kind then key. An org's own definitions are not
    listed."""
    require_runtime()
    with db.connect() as conn:
        return [summary_of(v) for v in registry.latest_platform(conn)]


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
        require_platform(conn, kind, key)
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
    `errors` lists every problem found, including ones in other definitions. `warnings` says how many
    definitions that teams built in their Studio the edit would break; it never names them."""
    require_runtime()
    with db.connect() as conn:
        edit = check_edit(conn, kind, key, body)
    return ValidateDefinitionResult(ok=not edit.errors, errors=edit.errors, warnings=edit.warnings)


@router.post(
    f"/definitions/{{kind}}/{KEY}:publish",
    operation_id="opsPublishDefinition",
    response_model=DefinitionDetail,
    status_code=201,
    responses={**RUNTIME_RESPONSES, **conflicts("VERSION_CONFLICT", NO_CHANGE)},
)
def ops_publish_definition(
    kind: DefinitionKind, key: PathId, body: PublishDefinitionRequest, actor: OpsWriter
) -> DefinitionDetail:
    """Validate, then publish the edit as the next version; an unknown kind/key is created as version 1.
    422 INVALID_DEFINITION (with `errors`) when it does not validate; 409 VERSION_CONFLICT when
    `baseVersion` is sent and someone has published since; 409 NO_CHANGE when it equals the latest
    version. The detail's `warnings` counts the definitions teams built that this version breaks."""
    require_runtime()
    with db.connect() as conn:
        edit = check_edit(conn, kind, key, body)
        edited, errors = edit.definition, edit.errors
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
            raise ApiProblem(409, NO_CHANGE, f"{kind}/{key} is unchanged.") from None
        detail = detail_of(conn, kind, key).model_copy(update={"warnings": edit.warnings})
        action = "definition.create" if before is None else "definition.publish"
        summary = (
            f"created v{published.version}" if before is None else f"v{before.version} → v{published.version}"
        )
        target = f"{kind}/{key}"
        live = workspace.live()
        if live:  # the publish and its audit entry commit together
            data = {"summary": summary}
            ops_state.audit(
                conn, actor.email, action, "definition", target, body.reason, data, actor_role=actor.role
            )
        conn.commit()
    if not live:
        with locked_store() as store:
            store.audit(actor, action, "definition", target, body.reason, summary)
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
