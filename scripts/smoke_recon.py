"""Live smoke: one pack (order-payment-reconciliation by default) end to end on the local stack.

    uv run --project apps/api python scripts/smoke_recon.py [--pack SLUG] [--model-env test|dev] [--live]

Needs `docker compose up -d` (Postgres 5442, Temporal 7243). Loads demo-app/.env into the process
environment without printing values, migrates the database, applies the definitions, starts a worker
subprocess and the API in-process (TestClient, dev auth), then drives one run: human review, write
approval, completion. Prints node statuses, AI spend and the verified work receipt; exits non-zero on
any failure.
"""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
# Per pack: the run input, the budget, how many approvals it raises, the review records the sandbox data
# gives with the fake models (checked with --model-env test only) and the reviewer's note.
PACKS = {
    "order-payment-reconciliation": {
        "input": "2026-10-06..2026-10-12",
        "budget": 2000,
        "expected_approvals": 1,
        "records": ["#1004", "#1007"],
        "feedback": "Checked each flagged order against its payment.",
    },
    "overdue-invoice-follow-up": {
        "input": {"as_of": "2026-10-13"},
        "budget": 1500,
        "expected_approvals": 1,
        "records": ["INV-0107", "INV-0098", "INV-0086", "INV-0104"],
        "feedback": "Checked each overdue invoice and its reminder stage.",
    },
    "refund-triage": {
        "input": {"since": "2026-10-06", "until": "2026-10-13"},
        "budget": 2000,
        "expected_approvals": 1,
        "records": ["#1003", "#1005", "#1088", "18f3a0c1d2e41103"],
        "feedback": "Checked each proposed refund decision against the policy.",
    },
    # No reviewer: the run goes triage -> one approval -> writes -> report (one grant covers every write).
    "order-to-cash-exception-desk": {
        "input": {"since": "2026-09-16", "until": "2026-10-16"},
        "budget": 2500,
        "expected_approvals": 1,
        "records": None,
        "feedback": None,
    },
}
WAIT_SECONDS = 180
# Run statuses the run can never leave; reaching one that was not awaited fails the smoke at once.
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
SEALED = "receipt.sealed"


def fail(message: str) -> NoReturn:
    print(f"SMOKE FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def load_env_file(path: Path) -> list[str]:
    """Export KEY=VALUE lines that are not already set; returns the key names (never values)."""
    loaded = []
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def require_port(host: str, port: int, name: str) -> None:
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError:
        fail(f"{name} is not reachable at {host}:{port}; run `docker compose up -d` from demo-app/")


def poll(api, run_id: str, statuses: set[str], timeout: int = WAIT_SECONDS) -> dict:
    deadline = time.time() + timeout
    run: dict = {}
    while time.time() < deadline:
        run = api.get(f"/v1/workflow-runs/{run_id}").json()
        status = run.get("status")
        if status in statuses:
            return run
        if status in TERMINAL:
            fail(f"run ended {status} while waiting for {sorted(statuses)}: {run.get('summary')}")
        time.sleep(0.5)
    fail(f"timeout after {timeout}s waiting for {sorted(statuses)}; last status {run.get('status')}")


def money(m: dict) -> str:
    return f"{m['amountMinor']} {m['currency']} (minor units)"


def drive(api, pack: str, model_env: str) -> int:
    spec = PACKS[pack]
    body = {"packSlug": pack, "input": spec["input"], "budgetMinor": spec["budget"]}
    res = api.post("/v1/workflow-runs", json=body)
    if res.status_code >= 300:
        fail(f"start run returned {res.status_code}: {res.text[:300]}")
    run_id = res.json()["id"]
    print("started", run_id, "pack", pack)

    if spec["records"] is not None:  # the pack has a reviewer step
        poll(api, run_id, {"WAITING_FOR_HUMAN"})
        tasks = [t for t in api.get("/v1/human-tasks/eligible").json() if t["runId"] == run_id]
        if not tasks:
            fail("run is waiting for a human but no eligible task was listed")
        task = tasks[0]
        full = api.get(f"/v1/human-tasks/{task['id']}").json()
        records = [r["id"] for r in full["records"]]
        print("human task", task["id"], "records", records)
        if model_env == "test" and records != spec["records"]:
            fail(f"review records {records}, expected {spec['records']}")
        if api.post(f"/v1/human-tasks/{task['id']}:claim").status_code >= 300:
            fail("claim failed")
        sub = api.post(
            f"/v1/human-tasks/{task['id']}:submit",
            json={
                "verdict": "APPROVED",
                "feedbackText": spec["feedback"],
                "recordCalls": {r: "explained" for r in records},
            },
        )
        if sub.status_code >= 300:
            fail(f"submit returned {sub.status_code}: {sub.text[:300]}")
        print("submitted", sub.json().get("state"))

    # Grant every approval the run raises, then check the pack raised exactly `expected_approvals`.
    approved: set[str] = set()
    deadline = time.time() + WAIT_SECONDS
    while True:
        final = poll(api, run_id, {"WAITING_FOR_EVENT"} | TERMINAL)
        if final["status"] in TERMINAL:
            break
        approvals = [
            a
            for a in api.get("/v1/approvals").json()
            if a["runId"] == run_id and a["status"] == "PENDING" and a["id"] not in approved
        ]
        if not approvals:  # the last grant is still being taken up
            if time.time() > deadline:
                fail("run is waiting for an event but no pending approval was listed")
            time.sleep(0.5)
            continue
        apr = approvals[0]
        print("approval", apr["id"], "|", apr["summary"])
        if api.post(f"/v1/approvals/{apr['id']}:approve").status_code >= 300:
            fail("approve failed")
        approved.add(apr["id"])

    if len(approved) != spec["expected_approvals"]:
        fail(f"the run raised {len(approved)} approvals, expected {spec['expected_approvals']}")
    receipt = api.get(f"/v1/workflow-runs/{run_id}/receipt").json()
    print("\nnode statuses")
    for node in final["nodes"]:
        print(f"  {node['id']:<22} {node['type']:<10} {node['status']}")
    spent = final["spent"]
    print("\nAI spend   ", money(spent["ai"]))
    print("human spend", money(spent["human"]))
    print("tool spend ", money(spent["tools"]))
    print("final status", final["status"])
    print("receipt verified", receipt["verified"], "entries", receipt["entries"])
    if final["status"] != "COMPLETED":
        fail(f"final status {final['status']}")
    if not receipt["verified"] or receipt["entries"] < 1:
        fail("receipt did not verify")
    last = receipt["items"][-1]["type"] if receipt["items"] else None
    if last != SEALED:
        fail(f"the receipt ends with {last!r}, not {SEALED!r}")
    if any(n["status"] == "FAILED" for n in final["nodes"]):
        fail("a node failed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", default="order-payment-reconciliation", choices=sorted(PACKS))
    parser.add_argument("--model-env", default="dev", choices=["test", "dev", "prod"])
    parser.add_argument("--live", action="store_true", help="use live connectors instead of the sandbox")
    args = parser.parse_args()

    keys = load_env_file(ROOT / ".env")
    print("loaded env keys:", ", ".join(sorted(keys)) or "(none)")
    # demo-app/.env may point at a hosted Temporal; the smoke always runs against the local compose stack.
    os.environ["TEMPORAL_TARGET"] = "127.0.0.1:7243"
    os.environ["TEMPORAL_NAMESPACE"] = "default"
    os.environ.pop("TEMPORAL_API_KEY", None)
    os.environ["NM_RUNTIME"] = "temporal"
    os.environ["NM_MODEL_ENV"] = args.model_env
    os.environ["NM_CONNECTOR_MODE"] = "live" if args.live else "sandbox"
    os.environ["NM_DEFS_AUTO_APPLY"] = "1"
    os.environ["AUTH_MODE"] = "dev"
    os.environ["NM_TASK_QUEUE"] = f"nm-smoke-{uuid.uuid4().hex[:6]}"
    if args.model_env != "test" and not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        fail(
            "GOOGLE_CLOUD_PROJECT is not set in demo-app/.env (needed for Gemini on Vertex AI; "
            "credentials come from `gcloud auth application-default login`)"
        )
    connectors, queue = os.environ["NM_CONNECTOR_MODE"], os.environ["NM_TASK_QUEUE"]
    print(f"pack {args.pack}, model env {args.model_env}, connectors {connectors}, queue {queue}")

    require_port("127.0.0.1", 5442, "Postgres")
    require_port("127.0.0.1", 7243, "Temporal")

    sys.path.insert(0, str(API_DIR))
    os.chdir(API_DIR)
    from app import db, settings
    from app.defs import registry
    from app.defs.loader import load_bundle

    with db.connect() as conn:
        db.migrate(conn)
        registry.apply_bundle(conn, load_bundle(settings.defs_dir()))
    db.reset_pool()
    print("migrated and applied definitions")

    log = tempfile.NamedTemporaryFile("w+", suffix=".log", prefix="smoke-worker-", delete=False)  # noqa: SIM115
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.worker"], cwd=API_DIR, env=os.environ.copy(), stdout=log, stderr=log
    )
    try:
        time.sleep(3)
        if worker.poll() is not None:
            log.flush()
            fail(f"worker exited early (see {log.name})")
        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app()) as api:
            return drive(api, args.pack, args.model_env)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=15)
        log.close()
        print("worker log:", log.name)


if __name__ == "__main__":
    sys.exit(main())
