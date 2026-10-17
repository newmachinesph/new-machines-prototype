"""What a connector tool is called where people read it: the Studio's palette and the run timeline.

A tool's `id` is for packs and fixtures (`gmail.list_threads`) and never changes; its optional `name` in the
connector file is for people, and tells apart two tools whose ids read alike (one listing emails, one listing
threads). Without a name the id is shown as words.
"""


def id_words(tool_id: str) -> str:
    """A tool id as words: "list_threads" -> "list threads"."""
    return tool_id.replace("_", " ")


def tool_name(tool: dict) -> str:
    """The Studio's name for a connector tool: its `name` when given, else its id as a sentence
    ("create_draft" -> "Create draft")."""
    return str(tool.get("name") or "").strip() or id_words(str(tool["id"])).capitalize()


def action_name(tool: dict | None, tool_id: str) -> str:
    """The run timeline's name for a tool call: the tool's `name` when the snapshot knows the tool and the
    connector file gives one, else the id as words ("append rows")."""
    return str((tool or {}).get("name") or "").strip() or id_words(tool_id)
