import logging
import os
from dataclasses import dataclass, field
from typing import Annotated, Any

import psycopg
import requests
from cachecontrol import CacheControl
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app import workspace
from app.errors import ApiProblem
from app.models.ops import OpsRole
from app.store import get_store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Actor:
    """Who is calling and the org they act in. Two actors are the same when user and org match; role,
    email and name describe the user."""

    user_id: str
    org_id: str
    role: str = field(default="owner", compare=False)
    email: str | None = field(default=None, compare=False)
    name: str | None = field(default=None, compare=False)
    org_name: str | None = field(default=None, compare=False)  # set in the live workspace
    email_verified: bool = field(default=False, compare=False)


DEMO_ORG_ID = "org_hp01"
DEMO_ACTOR = Actor(user_id="user_demo", org_id=DEMO_ORG_ID)

# auto_error=False: a missing or malformed header reaches get_actor as None, so the 401 is our problem+json
# rather than FastAPI's default. The scheme documents a bearer `securitySchemes` entry in the OpenAPI.
bearer = HTTPBearer(auto_error=False, description="Firebase ID token.")

CERTS_TIMEOUT_SECONDS = 5
# Google mints the token, our instance checks it: allow for their clocks differing slightly.
CLOCK_SKEW_SECONDS = 10


def is_dev_mode() -> bool:
    """Only an explicit AUTH_MODE=dev skips sign-in, so a missing setting fails closed."""
    return os.environ.get("AUTH_MODE") == "dev"


def check_auth_config() -> None:
    """Called at startup, so a deploy without its project fails to boot instead of failing every request."""
    if not is_dev_mode() and not os.environ.get("FIREBASE_PROJECT_ID"):
        raise RuntimeError(
            "Sign-in checks need FIREBASE_PROJECT_ID (or AUTH_MODE=dev for local development)."
        )


class _CertsRequest(Request):
    """google-auth's transport waits up to 120 s by default; a hung fetch would hold a worker that long."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=CERTS_TIMEOUT_SECONDS, **kwargs):
        return super().__call__(url, method, body, headers, timeout, **kwargs)


# Google's signing certificates carry Cache-Control headers; caching them saves a fetch on every request.
_certs_request = _CertsRequest(session=CacheControl(requests.Session()))


def _verified_claims(token: str) -> dict[str, Any]:
    """The token's claims, once its signature, audience, expiry and issuer check out and it names a user."""
    project_id = os.environ["FIREBASE_PROJECT_ID"]
    try:
        # Checks the signature against Google's certificates, the audience (our project) and expiry.
        claims = id_token.verify_firebase_token(
            token, _certs_request, audience=project_id, clock_skew_in_seconds=CLOCK_SKEW_SECONDS
        )
    except TransportError as error:
        # Not the user's fault: a 401 would sign them out of the app.
        detail = "Sign-in can't be checked right now. Try again shortly."
        raise ApiProblem(503, "AUTH_UNAVAILABLE", detail) from error
    except ValueError as error:
        raise ApiProblem(401, "AUTHENTICATION_REQUIRED", "Sign in again to continue.") from error
    # google-auth does not check the issuer, and every Firebase token must name a user.
    user_id = claims.get("sub")
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}" or not user_id:
        raise ApiProblem(401, "AUTHENTICATION_REQUIRED", "Sign in again to continue.")
    return claims


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiProblem(401, "AUTHENTICATION_REQUIRED", "Sign in to continue.")
    return credentials.credentials


def _suspended() -> ApiProblem:
    return ApiProblem(403, "TENANT_SUSPENDED", "This workspace is suspended. Contact New Machines support.")


def _demo_actor(credentials: HTTPAuthorizationCredentials | None) -> Actor:
    if is_dev_mode():
        return DEMO_ACTOR
    who = workspace.identity_from_claims(_verified_claims(_bearer_token(credentials)))
    return Actor(user_id=who.user_id, org_id=DEMO_ORG_ID, email=who.email, name=who.name)


def _live_actor(credentials: HTTPAuthorizationCredentials | None) -> Actor:
    if is_dev_mode():
        who = workspace.DEV_IDENTITY
    else:
        who = workspace.identity_from_claims(_verified_claims(_bearer_token(credentials)))
    try:
        member = workspace.membership(who)
    except psycopg.OperationalError as error:
        log.warning("The workspace of %s could not be read: %s", who.user_id, type(error).__name__)
        detail = "Your workspace can't be reached right now. Try again shortly."
        raise ApiProblem(503, "WORKSPACE_UNAVAILABLE", detail) from error
    if member.org_status == "suspended":
        raise _suspended()
    return Actor(
        user_id=who.user_id,
        org_id=member.org_id,
        role=member.role,
        email=who.email,
        name=who.name,
        org_name=member.org_name,
        email_verified=who.email_verified,
    )


def get_actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Actor:
    """Swappable auth seam for customer routes. AUTH_MODE=dev accepts any token or none; otherwise Firebase
    ID tokens are verified. In the demo workspace every signed-in user works in the one seeded org; in the
    live workspace each user works in their own org (`workspace.membership`), and the dev user is
    `dev-user`. A workspace that is suspended is locked out of every customer route."""
    if workspace.live():
        return _live_actor(credentials)
    actor = _demo_actor(credentials)
    tenant = get_store().tenants.get(actor.org_id)
    if tenant is not None and tenant.status == "suspended":
        raise _suspended()
    return actor


CurrentActor = Annotated[Actor, Depends(get_actor)]


# Operators ---------------------------------------------------------------------------------------------
# Staff sign in with the same Firebase project; an operator is a verified email on an allow list. The ops
# routes depend on `get_ops_actor` only, never `get_actor`, so a suspended tenant cannot lock staff out.


@dataclass(frozen=True)
class OpsActor:
    user_id: str
    email: str
    role: OpsRole


DEV_OPS_ACTOR = OpsActor(user_id="ops_demo", email="ops@newmachin.es", role="owner")
OPS_WRITER_ROLES: frozenset[OpsRole] = frozenset({"owner", "admin"})
# Staff sign in with Google or email and password. Anonymous, phone and custom-token sessions never qualify.
OPS_SIGN_IN_PROVIDERS = frozenset({"google.com", "password"})


def _email_list(name: str) -> frozenset[str]:
    """A comma-separated env var as lower-case emails. Unset or blank entries admit nobody."""
    return frozenset(e.strip().lower() for e in os.environ.get(name, "").split(",") if e.strip())


def ops_role_for(email: str) -> OpsRole | None:
    """Nobody is an owner outside dev mode; an email on both lists is an admin."""
    email = email.strip().lower()
    if email in _email_list("OPS_ADMIN_EMAILS"):
        return "admin"
    if email in _email_list("OPS_SUPPORT_EMAILS"):
        return "support"
    return None


def _ops_forbidden() -> ApiProblem:
    return ApiProblem(403, "OPS_FORBIDDEN", "This account is not on the New Machines operator team.")


def get_ops_actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> OpsActor:
    """AUTH_MODE=dev is an owner operator. Otherwise the Firebase ID token must carry a verified email that
    is on OPS_ADMIN_EMAILS or OPS_SUPPORT_EMAILS; anyone else gets 403."""
    if is_dev_mode():
        return DEV_OPS_ACTOR
    claims = _verified_claims(_bearer_token(credentials))
    email = claims.get("email")
    # `is not True`: only a real boolean true counts; a string "true" or a missing claim does not.
    if claims.get("email_verified") is not True or not isinstance(email, str) or not email.strip():
        raise _ops_forbidden()
    firebase = claims.get("firebase")
    provider = firebase.get("sign_in_provider") if isinstance(firebase, dict) else None
    if provider not in OPS_SIGN_IN_PROVIDERS:
        raise _ops_forbidden()
    role = ops_role_for(email)
    if role is None:
        raise _ops_forbidden()
    return OpsActor(user_id=claims["sub"], email=email.strip().lower(), role=role)


CurrentOps = Annotated[OpsActor, Depends(get_ops_actor)]


def require_ops_writer(actor: CurrentOps) -> OpsActor:
    """Mutations need admin or owner; support is read-only."""
    if actor.role not in OPS_WRITER_ROLES:
        raise ApiProblem(403, "OPS_FORBIDDEN", "Your operator role is read-only.")
    return actor


OpsWriter = Annotated[OpsActor, Depends(require_ops_writer)]
