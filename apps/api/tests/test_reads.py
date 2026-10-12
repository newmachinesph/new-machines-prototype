import pytest

ORG = "/v1/organizations/org_hp01"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/workflow-packs",
        "/v1/agents",
        "/v1/workflow-runs",
        "/v1/approvals",
        "/v1/human-tasks/eligible",
        "/v1/reviewer/earnings",
        "/v1/memory",
        "/v1/connections",
        f"{ORG}/policies",
        f"{ORG}/members",
        "/v1/tokens",
        f"{ORG}/attention",
    ],
)
def test_lists_return_non_empty_arrays(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list) and r.json()


def test_pack_by_slug(client):
    r = client.get("/v1/workflow-packs/order-payment-reconciliation")
    assert r.status_code == 200
    assert r.json()["name"] == "Order & Payment Reconciliation"


def test_run_detail_is_camel_case_without_nulls(client):
    body = client.get("/v1/workflow-runs/run_1042").json()
    assert body["packSlug"] == "order-payment-reconciliation"
    assert body["edges"][0]["from"] == "start"
    assert None not in [v for v in body.values()]
    assert body["deliverable"]["rows"]


def test_runs_list_is_newest_first_and_flags_detail(client):
    rows = client.get("/v1/workflow-runs").json()
    assert rows[0]["startedAt"] >= rows[1]["startedAt"]
    assert {r["id"]: r["hasDetail"] for r in rows}["run_1033"] is False


def test_eligible_tasks_hide_records(client):
    tasks = client.get("/v1/human-tasks/eligible").json()
    assert all(t["records"] == [] for t in tasks)
    assert client.get("/v1/human-tasks/ht_011").json()["records"]


def test_org_and_usage(client):
    assert client.get(ORG).json()["short"] == "Harbor & Pine"
    usage = client.get(f"{ORG}/usage").json()
    assert usage["ledger"] and usage["org"]["monthlyCap"]["amountMinor"] == 25000


@pytest.mark.parametrize(
    "path",
    [
        "/v1/workflow-runs/run_9999",
        "/v1/workflow-packs/nope",
        "/v1/human-tasks/ht_999",
    ],
)
def test_unknown_ids_are_404_problem(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_other_org_is_denied(client):
    r = client.get("/v1/organizations/org_other/members")
    assert r.status_code == 403
    assert r.json()["code"] == "TENANT_SCOPE_DENIED"
