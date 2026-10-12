ORG = "/v1/organizations/org_hp01"


def test_start_run_creates_a_running_run(client):
    body = {
        "packSlug": "order-payment-reconciliation",
        "input": "Google Sheets: Orders Oct 11",
        "budgetMinor": 5000,
    }
    r = client.post("/v1/workflow-runs", json=body, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 202
    run = r.json()
    assert run["id"] == "run_1048" and run["status"] == "RUNNING"
    assert client.get(f"/v1/workflow-runs/{run['id']}").status_code == 200
    assert client.get("/v1/workflow-runs").json()[0]["id"] == "run_1048"


def test_start_run_idempotency(client):
    body = {"packSlug": "order-payment-reconciliation", "input": "x", "budgetMinor": 5000}
    first = client.post("/v1/workflow-runs", json=body, headers={"Idempotency-Key": "same"}).json()
    again = client.post("/v1/workflow-runs", json=body, headers={"Idempotency-Key": "same"}).json()
    assert first["id"] == again["id"]
    changed = client.post(
        "/v1/workflow-runs", json={**body, "budgetMinor": 2000}, headers={"Idempotency-Key": "same"}
    )
    assert changed.status_code == 409 and changed.json()["code"] == "CONFLICT"


def test_start_run_rejects_unhired_pack_and_bad_body(client):
    r = client.post(
        "/v1/workflow-runs", json={"packSlug": "chargeback-evidence", "input": "x", "budgetMinor": 5000}
    )
    assert r.status_code == 403 and r.json()["code"] == "POLICY_DENIED"
    bad = client.post("/v1/workflow-runs", json={"packSlug": "order-payment-reconciliation"})
    assert bad.status_code == 422 and bad.json()["code"] == "SCHEMA_INVALID"


def test_approve_and_decline(client):
    assert client.post("/v1/approvals/apr_311:approve").json()["status"] == "GRANTED"
    again = client.post("/v1/approvals/apr_311:decline")
    assert again.status_code == 409 and again.json()["code"] == "CONFLICT"


def test_claim_and_submit_task(client):
    claimed = client.post("/v1/human-tasks/ht_011:claim").json()
    assert claimed["state"] == "CLAIMED"
    body = {
        "verdict": "REVISION_REQUIRED",
        "feedbackText": "Fixed three records.",
        "recordCalls": {"r1": "match"},
    }
    assert client.post("/v1/human-tasks/ht_011:submit", json=body).json()["state"] == "SUBMITTED"


def test_submit_without_claim_conflicts(client):
    body = {"verdict": "APPROVED", "feedbackText": "ok", "recordCalls": {}}
    r = client.post("/v1/human-tasks/ht_014:submit", json=body)
    assert r.status_code == 409


def test_memory_review_and_retract(client):
    cand = next(m for m in client.get("/v1/memory").json() if m["state"] == "CANDIDATE")
    done = client.post(
        f"/v1/memory-candidates/{cand['id']}:review", json={"decision": "approve", "text": "Edited."}
    )
    assert done.json()["state"] == "APPROVED" and done.json()["text"] == "Edited."
    approved = next(
        m for m in client.get("/v1/memory").json() if m["state"] == "APPROVED" and m["id"] != cand["id"]
    )
    assert client.post(f"/v1/memory/{approved['id']}:retract").json()["retracted"] is True


def test_disconnect_and_revoke_grant(client):
    conn = next(c for c in client.get("/v1/connections").json() if c["status"] == "connected" and c["grants"])
    grant = conn["grants"][0]
    r = client.request(
        "DELETE",
        "/v1/grants",
        params={"app": conn["app"], "install": grant["install"], "capability": grant["capability"]},
    )
    assert r.status_code == 204
    after = client.post(f"/v1/connections/{conn['app']}:disconnect").json()
    assert after["status"] == "not_connected" and after["grants"] == []


def test_install_returns_summary(client):
    r = client.post(
        f"{ORG}/agent-installations",
        json={"packSlug": "chargeback-evidence", "capMinor": 2000, "reviewerPool": False},
    )
    assert r.status_code == 201
    assert r.json()["summary"] == "Spending cap $20.00 per run. Reviewers: your team only."
    assert client.get("/v1/workflow-packs/chargeback-evidence").json()["installed"] is True


def test_invite_and_duplicate(client):
    ok = client.post(f"{ORG}/invitations", json={"email": "ana@example.com", "role": "Member"})
    assert ok.status_code == 201 and ok.json()["pending"] is True
    dup = client.post(f"{ORG}/invitations", json={"email": "ANA@example.com", "role": "Admin"})
    assert dup.status_code == 409


def test_tokens_create_and_revoke(client):
    r = client.post("/v1/tokens", json={"name": "Cursor", "scopes": ["runs:read"]})
    assert r.status_code == 201
    created = r.json()
    assert created["secret"].startswith("nm_pat_demo_") and created["token"]["last4"] == "DEMO"
    assert client.delete(f"/v1/tokens/{created['token']['id']}").status_code == 204
    empty = client.post("/v1/tokens", json={"name": "x", "scopes": []})
    assert empty.status_code == 422


def test_suggest_matches_a_pack(client):
    r = client.post("/v1/workflow-packs:suggest", json={"text": "reconcile orders and payouts every week"})
    body = r.json()
    assert body["simulated"] is True
    assert body["pack"]["slug"] == "order-payment-reconciliation"
    assert 3 <= len(body["steps"]) <= 5
