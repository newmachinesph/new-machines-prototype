"""What a run of another workspace's listed pack pins (sub-project D): the bundle of the approved version the
org's installation holds, until the org updates it (`live_catalog.upgrade`)."""

from dataclasses import dataclass

from app.defs import owners, registry
from app.defs.snapshot import build_snapshot
from app.runtime import gateway

# The approved listing version the installation holds (`installations.listing_version_id`), at its pinned
# pack version, of a listed listing published by the pack's private owner (the rule
# `registry.pinnable_version` applies to each pin). An installation that holds none (NULL) matches nothing:
# it fails closed instead of taking whichever version was approved last.
_INSTALLED_BUNDLE = (
    "SELECT v.id, v.definitions FROM installations i "
    "JOIN listings l ON l.kind = 'pack' AND l.definition_key = i.pack_slug AND l.status = 'listed' "
    "AND l.publisher_org_id = %(publisher)s "
    "JOIN listing_versions v ON v.listing_id = l.id AND v.definition_version = i.pack_version "
    "AND v.status = 'approved' AND v.id = i.listing_version_id "
    "WHERE i.org_id = %(org)s AND i.pack_slug = %(slug)s"
)


class Unavailable(LookupError):
    """The installation holds a version of another workspace's listed pack that cannot run now."""


@dataclass(frozen=True)
class Held:
    """What an installation of another workspace's listed pack holds: the approved listing version and the
    {(kind, key): version} pins of its bundle."""

    listing_version_id: str
    pins: dict[tuple[str, str], int]


def other_workspaces(owner: owners.Owner, org_id: str) -> bool:
    """Whether the definition is another workspace's private one: only such a pack or agent reaches the org by
    a listing."""
    return owner.kind == "org" and owner.id != org_id and owner.visibility == "private"


def installed_bundle(conn, org_id: str, pack_slug: str) -> Held | None:
    """The approved listing version the installation holds and its pins, for another workspace's listed pack;
    None for the platform's packs, the org's own, or one it has not added.

    Unavailable when the installation holds a version of another workspace's pack that no approved version of
    a listed listing exposes (unlisted, never approved, or no listing version held), or whose bundle pins
    another pack version: the run fails clearly instead of running another version at another price than the
    cap checked. (An org pack's slug is its key: `studio_build` writes "slug": key.)"""
    hire = conn.execute(
        "SELECT pack_version FROM installations WHERE org_id = %s AND pack_slug = %s", (org_id, pack_slug)
    ).fetchone()
    if hire is None:
        return None
    owner = registry.owner_of(conn, "pack", pack_slug)
    if not other_workspaces(owner, org_id):
        return None
    held = int(hire["pack_version"])
    row = conn.execute(
        _INSTALLED_BUNDLE, {"publisher": owner.id, "org": org_id, "slug": pack_slug}
    ).fetchone()
    if row is None:
        raise Unavailable(f"pack/{pack_slug}@{held} is not available to {org_id}")
    pins = {(d["kind"], d["key"]): int(d["version"]) for d in row["definitions"]}
    if pins.get(("pack", pack_slug)) != held:
        raise Unavailable(f"the approved bundle of pack/{pack_slug}@{held} pins another pack version")
    return Held(listing_version_id=row["id"], pins=pins)


def installed_pins(conn, org_id: str, pack_slug: str) -> dict[tuple[str, str], int] | None:
    """The pins of `installed_bundle`, or None."""
    held = installed_bundle(conn, org_id, pack_slug)
    return held.pins if held else None


def pinned_input_schema(conn, org_id: str, pack_slug: str, pins: dict) -> dict | None:
    """The run input schema of the pinned versions (the newest approved one may have changed it). Unavailable
    when a pinned definition is no longer available to the org."""
    try:
        snapshot = build_snapshot(conn, pack_slug, org_id, {}, set(), pins=pins)
    except LookupError as exc:
        if type(exc) is not LookupError:  # a KeyError or IndexError is a bug, not an unavailable pin
            raise
        raise Unavailable(str(exc)) from exc
    ref = gateway.contract_of(snapshot).get("input_schema_ref")
    schema = (snapshot["defs"].get("schema") or {}).get(str(ref)) if ref else None
    return schema["body"] if schema else None
