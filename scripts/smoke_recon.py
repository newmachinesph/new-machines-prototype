"""Live smoke: order-payment-reconciliation end to end on the local stack.

    uv run --project apps/api python scripts/smoke_recon.py [--model-env test|dev] [--live]

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
PACK = "order-payment-reconciliation"
RUN_INPUT = "2026-10-06..2026-10-12"
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


def drive(api) -> int:
    res = api.post("/v1/workflow-runs", json={"packSlug": PACK, "input": RUN_INPUT, "budgetMinor": 2000})
    if res.status_code >= 300:
        fail(f"start run returned {res.status_code}: {res.text[:300]}")
    run_id = res.json()["id"]
    print("started", run_id)

    poll(api, run_id, {"WAITING_FOR_HUMAN"})
    tasks = [t for t in api.get("/v1/human-tasks/eligible").json() if t["runId"] == run_id]
    if not tasks:
        fail("run is waiting for a human but no eligible task was listed")
    task = tasks[0]
    full = api.get(f"/v1/human-tasks/{task['id']}").json()
    records = [r["id"] for r in full["records"]]
    print("human task", task["id"], "records", records)
    if api.post(f"/v1/human-tasks/{task['id']}:claim").status_code >= 300:
        fail("claim failed")
    sub = api.post(
        f"/v1/human-tasks/{task['id']}:submit",
        json={
            "verdict": "APPROVED",
            "feedbackText": "Checked each flagged order against its payment.",
            "recordCalls": {r: "explained" for r in records},
        },
    )
    if sub.status_code >= 300:
        fail(f"submit returned {sub.status_code}: {sub.text[:300]}")
    print("submitted", sub.json().get("state"))

    poll(api, run_id, {"WAITING_FOR_EVENT"})
    approvals = [
        a for a in api.get("/v1/approvals").json() if a["runId"] == run_id and a["status"] == "PENDING"
    ]
    if not approvals:
        fail("run is waiting for an event but no pending approval was listed")
    apr = approvals[0]
    print("approval", apr["id"], "|", apr["summary"])
    if api.post(f"/v1/approvals/{apr['id']}:approve").status_code >= 300:
        fail("approve failed")

    final = poll(api, run_id, TERMINAL)
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
    if args.model_env == "dev" and not os.environ.get("ANTHROPIC_API_KEY"):
        fail("ANTHROPIC_API_KEY is not set in demo-app/.env (needed for --model-env dev)")
    connectors, queue = os.environ["NM_CONNECTOR_MODE"], os.environ["NM_TASK_QUEUE"]
    print(f"model env {args.model_env}, connectors {connectors}, queue {queue}")

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
            return drive(api)
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
