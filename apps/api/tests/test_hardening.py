import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from app import store as store_module
from app.auth import Actor
from app.idempotency import MAX_KEYS, once
from app.main import create_app
from app.store import get_store, reset_store

ORG = "/v1/organizations/org_hp01"
OTHER_ORG = "/v1/organizations/org_other"


# Errors ------------------------------------------------------------------------------------------------


def test_unexpected_error_is_problem_json_500_with_cors(monkeypatch):
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom", headers={"Origin": "http://localhost:3100"})
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "INTERNAL" and "kaboom" not in r.text
    assert r.headers["access-control-allow-origin"] == "http://localhost:3100"
    other = client.get("/boom", headers={"Origin": "https://evil.example"})
    assert other.status_code == 500 and "access-control-allow-origin" not in other.headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/approvals/apr_999:approve"),
        ("POST", "/v1/human-tasks/ht_999:claim"),
        ("POST", "/v1/connections/Nope:disconnect"),
        ("DELETE", "/v1/tokens/pat_nope"),
        ("POST", "/v1/memory/mem_999:retract"),
    ],
)
def test_unknown_ids_on_actions_are_404_problem(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"{OTHER_ORG}/invitations", {"email": "ana@example.com", "role": "Member"}),
        (
            f"{OTHER_ORG}/agent-installations",
            {"packSlug": "chargeback-evidence", "capMinor": 2000, "reviewerPool": False},
        ),
    ],
)
def test_other_org_actions_are_denied(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 403
    assert r.json()["code"] == "TENANT_SCOPE_DENIED"


def test_request_bodies_reject_unknown_keys(client):
    r = client.post("/v1/tokens", json={"name": "x", "scopes": ["runs:read"], "nmae": "typo"})
    assert r.status_code == 422 and r.json()["code"] == "SCHEMA_INVALID"


# Auth --------------------------------------------------------------------------------------------------


def test_dev_auth_mode_accepts_any_or_no_token(client):
    assert client.get("/v1/approvals").status_code == 200
    assert client.get("/v1/approvals", headers={"Authorization": "Bearer anything"}).status_code == 200
    assert client.get("/v1/approvals", headers={"Authorization": "Basic abc"}).status_code == 200


# CORS --------------------------------------------------------------------------------------------------


def preflight(client: TestClient, origin: str):
    return client.options(
        "/v1/approvals", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_cors_caches_preflight_and_refuses_other_origins(client):
    ok = preflight(client, "http://localhost:3100")
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3100"
    assert ok.headers["access-control-max-age"] == "600"
    assert "access-control-allow-origin" not in preflight(client, "https://evil.example").headers
    simple = client.get("/v1/approvals", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_allowed_origins_are_trimmed_and_lose_trailing_slashes(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", " https://app.example.com/ , http://localhost:3100,")
    client = TestClient(create_app())
    for origin in ("https://app.example.com", "http://localhost:3100"):
        assert preflight(client, origin).headers["access-control-allow-origin"] == origin


# Idempotency -------------------------------------------------------------------------------------------


class Body(BaseModel):
    value: int


def test_idempotency_keys_are_scoped_to_the_actor():
    reset_store()
    ana, ben = Actor(user_id="u_ana", org_id="org_1"), Actor(user_id="u_ben", org_id="org_1")
    first = once("scope", ana, "k", Body(value=1), lambda: "ana's")
    assert once("scope", ben, "k", Body(value=2), lambda: "ben's") == "ben's"
    assert once("scope", ana, "k", Body(value=1), lambda: "again") == first


def test_idempotency_cache_evicts_the_oldest_keys():
    reset_store()
    actor = Actor(user_id="u", org_id="o")
    for i in range(MAX_KEYS + 1):
        once("scope", actor, f"k{i}", Body(value=i), lambda i=i: i)
    assert len(get_store().idempotency) == MAX_KEYS
    assert once("scope", actor, "k0", Body(value=0), lambda: "made again") == "made again"
    assert once("scope", actor, f"k{MAX_KEYS}", Body(value=MAX_KEYS), lambda: "made again") == MAX_KEYS


# Needs you ---------------------------------------------------------------------------------------------


def hrefs(client: TestClient) -> list[str]:
    return [item["href"] for item in client.get(f"{ORG}/attention").json()]


def test_attention_follows_pending_approvals_and_memory_candidates(client):
    items = client.get(f"{ORG}/attention").json()
    approval = next(i for i in items if i["href"] == "/app/approvals")
    assert approval["title"] == "Approve one outgoing email"
    assert approval["detail"] == "Send a payment reminder to Cedarline Home"
    assert [i["when"] for i in items] == sorted((i["when"] for i in items), reverse=True)

    assert client.post("/v1/approvals/apr_311:approve").status_code == 200
    assert "/app/approvals" not in hrefs(client)

    assert "/app/memory" in hrefs(client)
    client.post("/v1/memory-candidates/mem_221:review", json={"decision": "reject"})
    assert "/app/memory" not in hrefs(client)
    assert len(hrefs(client)) == 2  # the other items are unchanged


# Fixtures ----------------------------------------------------------------------------------------------


def add_typo_to_member(rows):
    rows[0]["emial"] = rows[0]["email"]


def add_nested_typo_to_approval(rows):
    rows[0]["digest"][0]["lable"] = "Workspace"


@pytest.mark.parametrize(
    ("name", "kind", "typo"),
    [
        ("members", list[store_module.Member], add_typo_to_member),
        ("approvals", list[store_module.Approval], add_nested_typo_to_approval),
    ],
)
def test_fixture_typos_still_fail(tmp_path, monkeypatch, name, kind, typo):
    rows = json.loads((store_module.FIXTURES / f"{name}.json").read_text("utf-8"))
    typo(rows)
    (tmp_path / f"{name}.json").write_text(json.dumps(rows), "utf-8")
    monkeypatch.setattr(store_module, "FIXTURES", tmp_path)
    with pytest.raises(ValidationError):
        store_module._load(name, kind)
