"""Test-only API launcher for the journey specs. Not product code.

AUTH_MODE=dev signs every request in as one user (`workspace.DEV_IDENTITY`), so a single API process cannot
show an owner, a member, a reviewer and a second workspace. This launcher serves the real app and overrides
only the customer actor: a bearer token `qa.<user>` (sent by the journey specs, never by a real client)
becomes a verified identity `<user>@qa.example`, provisioned and resolved through the real
`workspace.membership`. Any other request falls back to the app's own `get_actor`.

Run from apps/api (it needs AUTH_MODE=dev and NM_WORKSPACE=live, see playwright.journeys.config.ts):
    uv run python ../web/e2e/journeys/support/qa_api.py --port 8600
"""

import argparse
import os
import sys
from typing import Annotated

sys.path.insert(0, os.getcwd())

import uvicorn  # noqa: E402
from fastapi import Depends  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402

from app import auth, workspace  # noqa: E402
from app.errors import ApiProblem  # noqa: E402
from app.main import app  # noqa: E402

QA_PREFIX = "qa."


def qa_actor(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(auth.bearer)],
) -> auth.Actor:
    token = credentials.credentials if credentials else ""
    if not token.startswith(QA_PREFIX):
        return auth.get_actor(credentials)
    user = token[len(QA_PREFIX) :]
    if not user.isidentifier():
        raise ApiProblem(401, "AUTHENTICATION_REQUIRED", "Bad QA user.")
    who = workspace.Identity(
        user_id=f"qa_{user}", email=f"{user}@qa.example", email_verified=True, name=user.capitalize()
    )
    member = workspace.membership(who)
    if member.org_status == "suspended":
        raise ApiProblem(403, "TENANT_SUSPENDED", "This workspace is suspended.")
    return auth.Actor(
        user_id=who.user_id,
        org_id=member.org_id,
        role=member.role,
        email=who.email,
        name=who.name,
        org_name=member.org_name,
        email_verified=True,
    )


app.dependency_overrides[auth.get_actor] = qa_actor

if __name__ == "__main__":
    if os.environ.get("AUTH_MODE") != "dev" or os.environ.get("K_SERVICE"):
        raise SystemExit("qa_api.py runs only locally with AUTH_MODE=dev.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
