import pytest
import requests
from google.auth.exceptions import TransportError

from app import auth
from app.auth import Actor
from app.main import create_app

PROJECT = "nm-demo-test"
CLAIMS = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "sub": "uid_123"}


@pytest.fixture
def firebase_mode(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)


def stub_verifier(monkeypatch, result):
    """Replace Google's verifier so no test fetches signing keys over the network."""
    calls = []

    def verify(token, request, audience=None, clock_skew_in_seconds=0):
        calls.append((token, audience, clock_skew_in_seconds))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(auth.id_token, "verify_firebase_token", verify)
    return calls


def assert_sign_in_required(r):
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.usefixtures("firebase_mode")
def test_a_verified_token_reaches_the_route_with_the_project_as_audience(client, monkeypatch):
    calls = stub_verifier(monkeypatch, CLAIMS)
    r = client.get("/v1/approvals", headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 200
    # A little clock skew, so a token Google minted a moment ago is not "used too early".
    assert calls == [("good-token", PROJECT, 10)]


def test_sign_in_is_checked_unless_dev_mode_is_set_explicitly(client, monkeypatch):
    monkeypatch.delenv("AUTH_MODE")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    stub_verifier(monkeypatch, CLAIMS)
    assert_sign_in_required(client.get("/v1/approvals"))


@pytest.mark.usefixtures("firebase_mode")
def test_when_google_cannot_be_reached_the_api_says_so_instead_of_signing_the_user_out(client, monkeypatch):
    stub_verifier(monkeypatch, TransportError("certificate fetch timed out"))
    r = client.get("/v1/approvals", headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "AUTH_UNAVAILABLE"


@pytest.mark.usefixtures("firebase_mode")
def test_the_signed_in_user_acts_in_the_shared_demo_workspace(monkeypatch):
    stub_verifier(monkeypatch, CLAIMS)
    credentials = auth.HTTPAuthorizationCredentials(scheme="Bearer", credentials="good-token")
    assert auth.get_actor(credentials) == Actor(user_id="uid_123", org_id="org_hp01")


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}])
def test_a_missing_or_non_bearer_token_is_refused_without_verifying(client, monkeypatch, headers):
    calls = stub_verifier(monkeypatch, CLAIMS)
    assert_sign_in_required(client.get("/v1/approvals", headers=headers))
    assert calls == []


@pytest.mark.usefixtures("firebase_mode")
def test_a_token_google_rejects_is_refused(client, monkeypatch):
    stub_verifier(monkeypatch, ValueError("Token expired"))
    assert_sign_in_required(client.get("/v1/approvals", headers={"Authorization": "Bearer stale"}))


@pytest.mark.usefixtures("firebase_mode")
@pytest.mark.parametrize(
    "claims",
    [
        {**CLAIMS, "iss": "https://securetoken.google.com/another-project"},
        {**CLAIMS, "sub": ""},
        {key: value for key, value in CLAIMS.items() if key != "sub"},
    ],
)
def test_a_token_from_another_issuer_or_without_a_user_is_refused(client, monkeypatch, claims):
    stub_verifier(monkeypatch, claims)
    assert_sign_in_required(client.get("/v1/approvals", headers={"Authorization": "Bearer odd"}))


def test_certificate_fetches_give_up_after_a_few_seconds(monkeypatch):
    seen = {}

    class Session:
        def request(self, method, url, data=None, headers=None, timeout=None, **kwargs):
            seen["timeout"] = timeout
            raise requests.ConnectionError("stop here")

    monkeypatch.setattr(auth._certs_request, "session", Session())
    with pytest.raises(TransportError):
        auth._certs_request("https://example.test/certs")
    assert seen["timeout"] == 5


def test_firebase_mode_without_a_project_refuses_to_start(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="FIREBASE_PROJECT_ID"):
        create_app()
