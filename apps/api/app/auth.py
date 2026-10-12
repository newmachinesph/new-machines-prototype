import os
from dataclasses import dataclass
from typing import Annotated

import requests
from cachecontrol import CacheControl
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from app.errors import ApiProblem


@dataclass(frozen=True)
class Actor:
    user_id: str
    org_id: str


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


def _verified_user_id(token: str) -> str:
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
    return user_id


def get_actor(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Actor:
    """Swappable auth seam. AUTH_MODE=dev accepts any token or none; otherwise Firebase ID tokens are
    verified. Every signed-in user works in the one seeded demo workspace."""
    if is_dev_mode():
        return DEMO_ACTOR
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiProblem(401, "AUTHENTICATION_REQUIRED", "Sign in to continue.")
    return Actor(user_id=_verified_user_id(credentials.credentials), org_id=DEMO_ORG_ID)


CurrentActor = Annotated[Actor, Depends(get_actor)]
