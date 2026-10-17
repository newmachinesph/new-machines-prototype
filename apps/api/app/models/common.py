import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints
from pydantic.alias_generators import to_camel
from pydantic.json_schema import SkipJsonSchema


class Model(BaseModel):
    """camelCase on the wire, snake_case in Python.

    Response models ignore unknown keys and so export no `additionalProperties: false`: the web's generated
    validators must tolerate a field the backend adds later. Fixtures are still loaded with `extra="forbid"`
    (see `store._load`), so a typo in a fixture fails the tests.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class RequestModel(Model):
    """Request bodies reject unknown keys, so a client typo is a 422 rather than a silently dropped field."""

    model_config = ConfigDict(extra="forbid")


class Money(Model):
    amount_minor: int
    currency: Literal["USD"] = "USD"


def money_text(amount_minor: int, currency: str = "USD") -> str:
    """Minor units as display text: "$1,234.50" for USD, "1,234.50 EUR" for other currencies."""
    sign = "-" if amount_minor < 0 else ""
    value = f"{abs(amount_minor) / 100:,.2f}"
    return f"{sign}${value}" if currency == "USD" else f"{sign}{value} {currency}"


Actor = Literal["machine", "human", "policy", "system", "buyer"]
OutcomeStage = Literal["executed", "verified", "accepted", "settlement"]
StageState = Literal["done", "pending", "failed", "blocked", "not_required"]
Opt = SkipJsonSchema[None]  # use as `str | Opt = None`: optional in the schema, never null

# A memory item's text, as the operator console and a workspace's owners add it.
MAX_MEMORY_TEXT = 2000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # every control character but tab and newline


def _printable(text: str) -> str:
    """NUL cannot be stored in Postgres text, and no other control character belongs in a rule."""
    if _CONTROL_CHARS.search(text):
        raise ValueError("control characters are not allowed")
    return text


MemoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MEMORY_TEXT),
    AfterValidator(_printable),
]
