from typing import Literal

from pydantic import BaseModel, ConfigDict
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


Actor = Literal["machine", "human", "policy", "system", "buyer"]
OutcomeStage = Literal["executed", "verified", "accepted", "settlement"]
StageState = Literal["done", "pending", "failed", "blocked", "not_required"]
Opt = SkipJsonSchema[None]  # use as `str | Opt = None`: optional in the schema, never null
