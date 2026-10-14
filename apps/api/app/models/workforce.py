"""The workforce: who reviews a hire's human tasks (sub-project B)."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool, StringConstraints

from app.models.common import Model, RequestModel
from app.models.org import MemberRole

# Who reviews a hire's human tasks: only the org's reviewers, only the New Machines reviewer network, or the
# org's reviewers first with the network after 30 minutes unclaimed (the default).
ReviewerPool = Literal["team", "network", "team_then_network"]
DEFAULT_REVIEWER_POOL: ReviewerPool = "team_then_network"

EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class OrgReviewer(Model):
    """A member with the reviewer capability, or a pending Reviewer invitation."""

    email: str
    name: str
    role: MemberRole
    pending: bool


class OrgReviewers(Model):
    """The org's reviewers, active first, and its switch for the New Machines reviewer network."""

    allow_network: bool
    reviewers: list[OrgReviewer]


class AddReviewerRequest(RequestModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)


class RemoveReviewerRequest(RequestModel):
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)


class ReviewerNetworkRequest(RequestModel):
    allow: bool


ReviewerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Language = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40)]
Skill = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class NetworkProfile(Model):
    """The signed-in user's profile as a New Machines network reviewer. `suspended`: New Machines paused
    it."""

    enabled: bool
    suspended: bool
    name: str
    languages: list[str]
    skills: list[str]


class NetworkProfileRequest(RequestModel):
    """The user's switch "Review for the network" and their profile. Entries are trimmed; repeated languages
    or skills are kept once (compared without case, the first spelling kept)."""

    enabled: StrictBool
    name: ReviewerName
    languages: list[Language] = Field(default_factory=list, max_length=10)
    skills: list[Skill] = Field(default_factory=list, max_length=20)
