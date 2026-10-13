"""Plain data types shared by the loader, validator and registry."""

from dataclasses import dataclass, field

KINDS = (
    "taxonomy",
    "models",
    "pack",
    "workflow",
    "contract",
    "agent",
    "connector",
    "decision_rules",
    "memory_space",
    "schema",
)


@dataclass(frozen=True)
class Definition:
    kind: str
    key: str
    body: dict  # parsed YAML/JSON minus kind/key
    files: dict[str, str] = field(default_factory=dict)  # Markdown by path relative to the folder (agents)
    path: str = ""  # source path relative to the definitions root


@dataclass(frozen=True)
class Bundle:
    items: dict[tuple[str, str], Definition]

    def get(self, kind: str, key: str) -> Definition | None:
        return self.items.get((kind, key))

    def of(self, kind: str) -> list[Definition]:
        return [d for (k, _), d in sorted(self.items.items()) if k == kind]


@dataclass(frozen=True)
class DefError:
    kind: str
    key: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.kind}/{self.key} ({self.path}): {self.message}"


def path_for(kind: str, key: str) -> str:
    """Canonical source path of a definition, relative to the definitions root.

    Pack-scoped kinds (pack, workflow, contract) are keyed by the pack slug; schema keys are
    `<pack-slug>/<file stem>`. Agent `files` live under `agents/<key>/`.
    """
    if kind in ("taxonomy", "models"):
        return f"{kind}.yaml"
    if kind in ("pack", "workflow", "contract"):
        return f"packs/{key}/{kind}.yaml"
    if kind == "agent":
        return f"agents/{key}/agent.yaml"
    if kind == "connector":
        return f"connectors/{key}.yaml"
    if kind == "decision_rules":
        return f"decisions/{key}.yaml"
    if kind == "memory_space":
        return f"memory/{key}.yaml"
    if kind == "schema":
        slug, _, stem = key.partition("/")
        return f"packs/{slug}/schemas/{stem}.json"
    raise ValueError(f"unknown definition kind: {kind}")
