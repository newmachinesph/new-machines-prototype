from typing import Literal

from pydantic import Field

from app.models.common import Model, Opt, RequestModel
from app.models.org import McpToken
from app.models.work import ReviewVerdict


class SuggestRequest(RequestModel):
    text: str = Field(min_length=3, max_length=500)


class InstallRequest(RequestModel):
    cap_minor: int = Field(gt=0)
    reviewer_pool: bool
    pack_slug: str


class Installation(Model):
    pack_slug: str
    cap_minor: int
    reviewer_pool: bool
    summary: str


class StartRunRequest(RequestModel):
    pack_slug: str
    input: str = Field(min_length=1, max_length=200)
    budget_minor: int = Field(gt=0, le=100_000)
    note: str | Opt = Field(default=None, max_length=500)


class SubmitReviewRequest(RequestModel):
    verdict: ReviewVerdict
    feedback_text: str = Field(min_length=1, max_length=4000)
    record_calls: dict[str, str]


class MemoryReviewRequest(RequestModel):
    decision: Literal["approve", "reject"]
    text: str | Opt = Field(default=None, max_length=1000)


class InviteRequest(RequestModel):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["Member", "Admin"]


class CreateTokenRequest(RequestModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal["agents:read", "runs:read", "runs:start", "approvals:list"]] = Field(min_length=1)


class CreatedToken(Model):
    token: McpToken
    secret: str
