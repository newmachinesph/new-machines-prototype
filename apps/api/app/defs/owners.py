"""Who owns a definition, and the key namespace that keeps owners apart.

A definition with no `definition_owners` row belongs to the platform and is in the marketplace. An org's own
definitions are keyed `<namespace>--<name>`, the namespace coming from the org id, so two orgs never collide.
Platform keys never contain "--" (the definitions console refuses them), so no org can take one.
"""

import re
from dataclasses import dataclass
from typing import Literal

OwnerKind = Literal["platform", "org", "developer"]
Visibility = Literal["private", "marketplace"]

SEPARATOR = "--"
NAME_MAX = 40
_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Owner:
    kind: OwnerKind
    id: str | None = None
    visibility: Visibility = "marketplace"


PLATFORM = Owner("platform")


def org_owner(org_id: str) -> Owner:
    """An org's own definition: only that org sees it ("Only my company")."""
    return Owner("org", org_id, "private")


def org_namespace(org_id: str) -> str:
    """`org_3f2a9c1b7d4e5f60` -> `org-3f2a9c1b7d4e5f60`: lowercase letters and digits after "org-"."""
    return "org-" + _NOT_ALNUM.sub("", org_id.lower().removeprefix("org_"))


def org_key(org_id: str, name: str) -> str:
    return f"{org_namespace(org_id)}{SEPARATOR}{name}"


def is_name(name: str) -> bool:
    """A key's name part: lowercase words of letters and digits joined by single hyphens, at most 40."""
    return len(name) <= NAME_MAX and _NAME.fullmatch(name) is not None


def in_org(key: str, org_id: str) -> bool:
    return key.startswith(org_namespace(org_id) + SEPARATOR)


def name_of(key: str) -> str:
    """The part after the namespace; the whole key when it has none."""
    return key.split(SEPARATOR, 1)[1] if SEPARATOR in key else key


def is_reserved(key: str) -> bool:
    """Owner-namespaced keys contain "--"; the definitions console and files never create them."""
    return SEPARATOR in key


def slugify(text: str) -> str:
    """A key name from a display name: "Invoice nudges!" -> "invoice-nudges", "2026 plan" -> "x-2026-plan".
    Text with no Latin letter or digit (such as Japanese) gives "untitled"."""
    words = _NOT_ALNUM.sub("-", text.lower()).strip("-")
    if not words:
        return "untitled"
    if not words[0].isalpha():
        words = f"x-{words}"
    return words[:NAME_MAX].rstrip("-")
