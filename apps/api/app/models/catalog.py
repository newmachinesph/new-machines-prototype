from typing import Literal

from pydantic import Field

from app.models.common import Model, Money, Opt


class Agent(Model):
    id: str
    version: str
    name: str
    publisher: str
    summary: str
    capabilities: list[str]
    regions: list[str]
    certified: bool


class PassportResult(Model):
    label: str
    value: float
    note: str | Opt = None


class TrustPassport(Model):
    tested_on: str
    tested_by: str
    cohort: str
    sample_size: int
    results: list[PassportResult]
    limitations: list[str]
    retest_triggers: list[str]


class PackConnector(Model):
    app: str
    access: Literal["read", "write (approval)", "write"]
    mocked: bool | Opt = None


class PackEstimate(Model):
    ai_min: Money
    ai_max: Money
    human_max: Money


class Pack(Model):
    slug: str
    name: str
    version: str
    publisher: str
    category: str
    outcome: str
    description: str
    agents: list[str]
    connectors: list[PackConnector]
    human_review: str
    estimate: PackEstimate
    installed: bool
    certified: bool
    passport: TrustPassport | Opt = None
    risk_class: Literal["low", "medium", "high"]
    regions: list[str]
    runs30d: int | Opt = Field(default=None, alias="runs30d")
    # From the pack definition: a taxonomy function id and industry ids (none for packs without one).
    function: str | Opt = None
    industries: list[str] = Field(default_factory=list)


class Suggestion(Model):
    pack: Pack | Opt = None
    steps: list[str]
    simulated: bool


class TaxonomyEntry(Model):
    id: str
    name: str


class Taxonomy(Model):
    functions: list[TaxonomyEntry]
    industries: list[TaxonomyEntry]
