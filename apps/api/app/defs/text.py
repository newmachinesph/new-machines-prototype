"""A definition's main file as submitted (the definitions console, a Studio workflow import): JSON for a
schema, YAML without anchors or aliases for everything else."""

import json

import yaml


class Unparseable(Exception):
    """The submitted text cannot be read; the message is safe to show to the user."""


def has_anchor(text: str) -> bool:
    """True when the YAML uses an anchor or alias, which can expand into a huge structure."""
    return any(
        isinstance(e, yaml.AliasEvent) or getattr(e, "anchor", None) is not None for e in yaml.parse(text)
    )


def parse_text(kind: str, text: str) -> dict:
    """The submitted main file as a mapping. Raises Unparseable with a user-facing message."""
    try:
        if kind == "schema":
            data = json.loads(text)
        elif has_anchor(text):
            raise Unparseable("YAML anchors and aliases (& and *) are not allowed.")
        else:
            data = yaml.safe_load(text)
    except json.JSONDecodeError as exc:
        raise Unparseable(f"JSON is not valid: line {exc.lineno}, column {exc.colno}: {exc.msg}.") from None
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        problem = (exc.problem or "cannot be read").replace("<stream end>", "the end of the text")
        raise Unparseable(f"YAML is not valid: {where}{problem}.") from None
    except yaml.YAMLError:
        raise Unparseable("YAML is not valid.") from None
    except RecursionError:  # the composer recurses per level of nesting
        raise Unparseable("YAML is nested too deeply.") from None
    if not isinstance(data, dict):
        raise Unparseable("The top level must be a mapping.")
    return data
