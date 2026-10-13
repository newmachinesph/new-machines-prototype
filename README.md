# New Machines demo app

## Local stack

Postgres (pgvector) and a Temporal dev server run from `compose.yaml`:

```bash
docker compose up -d        # from demo-app/
docker compose ps           # postgres and temporal should report healthy
```

| Service     | Host address            | Notes                                  |
|-------------|-------------------------|----------------------------------------|
| Postgres    | `127.0.0.1:5442`        | user/password/db `nm`; tests use `nm_test` |
| Temporal    | `127.0.0.1:7243`        | gRPC frontend, namespace `default`; history in volume `nm-temporal` |
| Temporal UI | `http://127.0.0.1:8243` |                                        |

Use `127.0.0.1` rather than `localhost` on Windows: `localhost` resolves to `::1` first and stalls
about 20 seconds per connection because the containers bind IPv4 only.

Environment variables (all optional, read at call time by `apps/api/app/settings.py`):

| Variable | Default |
|----------|---------|
| `NM_DATABASE_URL` | `postgresql://nm:nm@127.0.0.1:5442/nm` |
| `NM_TEST_DATABASE_URL` | `postgresql://nm:nm@127.0.0.1:5442/nm_test` |
| `NM_RUNTIME` | `off` (`temporal` enables the real runtime) |
| `TEMPORAL_TARGET` / `TEMPORAL_NAMESPACE` | `127.0.0.1:7243` / `default` |
| `NM_TASK_QUEUE` | `nm-packs` |
| `NM_MODEL_ENV` | `test` (`test`, `dev`, `prod`) |
| `NM_CONNECTOR_MODE` | `sandbox` (`auto`, `sandbox`, `live`) |
| `NM_DEFS_DIR` | `<repo>/definitions` |
| `NM_DEFS_AUTO_APPLY` | unset |

Migrations in `apps/api/migrations/*.sql` are applied by `app.db.migrate`. The API suite needs no
database; only tests that request the `db` fixture touch `nm_test` (created on demand).

Both keep their state in named volumes (`nm-pg`, `nm-temporal`), so runs survive `docker compose restart`
or `down`/`up`. Reset all local state (database and Temporal history):

```bash
docker compose down -v
```

## Run the real workflow locally

Order-payment reconciliation runs on the real runtime: a generic Temporal workflow (`PackRunner`) walks
the versioned definitions in `definitions/`, the Tool Gateway calls sandbox connectors, state lands in
Postgres, and every step is written to a hash-chained work receipt.

One command drives a whole run (start, human review, write approval, completion) and checks the receipt:

```bash
docker compose up -d
uv run --project apps/api python scripts/smoke_recon.py --model-env test   # fake model provider, no keys
uv run --project apps/api python scripts/smoke_recon.py --model-env dev    # real model provider
```

`--model-env dev` reads the provider key (`ANTHROPIC_API_KEY`) from `demo-app/.env`; the script never prints
values. Model profiles and the provider mapping per environment live in `definitions/models.yaml`.
`--live` swaps the sandbox connectors for live ones, and works only once that is set up: `COMPOSIO_API_KEY`
and `DEMO_USER_UID` in `demo-app/.env`, Shopify, Stripe and Google Sheets accounts connected in Composio for
that user, and a real `spreadsheetId` in place of the placeholder `demo-reconciliation-sheet` in
`definitions/packs/order-payment-reconciliation/workflow.yaml` (the `write` node). The script always targets
the local Temporal (`127.0.0.1:7243`), whatever `.env` says, and exits non-zero if any step fails, including
when the receipt does not end with its seal. Typical output: every node `COMPLETED`, AI spend of a few cents
(minor units), `receipt verified True`.

To run the pieces yourself, from `apps/api` with `demo-app/.env` loaded:

```bash
# worker
NM_RUNTIME=temporal NM_MODEL_ENV=dev uv run --env-file ../../.env python -m app.worker
# API on 8400 (applies definitions at startup)
NM_RUNTIME=temporal NM_MODEL_ENV=dev NM_DEFS_AUTO_APPLY=1 AUTH_MODE=dev ALLOWED_ORIGINS=http://localhost:3400 \
  uv run --env-file ../../.env uvicorn app.main:app --port 8400
```

Validate or apply the definition files without the API: `uv run python -m app.defs validate|apply|export`.
The API's startup apply (`NM_DEFS_AUTO_APPLY=1`) validates first and applies nothing when a file is invalid
(the errors are logged; the API still starts). Neither it nor `apply` replaces a definition whose latest
version was published from the operator console: a restart keeps the console edit, and a file changed since
its last apply is skipped with a warning. `python -m app.defs apply --force` applies the files over console
versions.
Human tasks and approvals appear in the customer app; the operator console (`apps/ops`) shows definitions,
agents, work contracts, memory and each run's work receipt. A decision is recorded before its workflow is
signalled; if the signal is lost, the same person sending the same decision again re-sends it. A run whose
workflow Temporal no longer has is ended `FAILED`.

`apps/api/tests/test_replay.py` replays a recorded `PackRunner` history against the current workflow code;
re-record it (`NM_RECORD_HISTORY=1 uv run pytest tests/test_replay.py`) only for a change meant to break
replay, after in-flight runs have finished.

## Build the API image

The Dockerfile lives in `apps/api` but builds from the demo-app root, so the image carries `definitions/`
(and sets `NM_DEFS_DIR` / `NM_SCHEMAS_DIR` to it). `.dockerignore` and `.gcloudignore` at the root keep
secrets, `node_modules` and the other apps out of the build context.

```bash
# from demo-app/
docker build -f apps/api/Dockerfile -t nm-api .
docker run --rm -p 8080:8080 -e AUTH_MODE=dev nm-api        # GET /healthz -> {"status":"ok"}

# Cloud Build, then deploy the pushed image
gcloud builds submit --project nm-demo-iu7uo4 --region asia-south1 --config apps/api/cloudbuild.yaml \
  --substitutions _IMAGE=asia-south1-docker.pkg.dev/nm-demo-iu7uo4/nm/nm-api:<tag> .
gcloud run deploy nm-api --project nm-demo-iu7uo4 --region asia-south1 \
  --image asia-south1-docker.pkg.dev/nm-demo-iu7uo4/nm/nm-api:<tag>
```

## Run everything in one Cloud Run service

The API image can host the runtime: with `NM_EMBEDDED_WORKER=1` (and `NM_RUNTIME=temporal`) the PackRunner
worker starts inside the API process after migrations and definitions are applied, on its own thread and
event loop, and stops on shutdown. A worker or Temporal failure is logged and retried with backoff; the API
keeps serving. One service then runs against Cloud SQL and Temporal Cloud, with no separate worker.

Environment variables (names only; put secrets in Secret Manager):

- `NM_RUNTIME=temporal`, `NM_EMBEDDED_WORKER=1`, `NM_DEFS_AUTO_APPLY=1`, `NM_WORKSPACE=demo|live`
- `NM_DATABASE_URL`: Cloud SQL over the unix socket, passed to the driver untouched:
  `postgresql://USER:PASS@/DB?host=/cloudsql/PROJECT:REGION:INSTANCE`
- `TEMPORAL_TARGET`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY` (the key alone switches on TLS, so regional
  `*.api.temporal.io:7233` endpoints work as well as `*.tmprl.cloud:7233`), `NM_TASK_QUEUE`
- `NM_WORKER_CONCURRENCY` (concurrent activities, default 8), `NM_DB_POOL_MAX` (Postgres pool, default 8;
  activity threads never exceed it)
- `NM_MODEL_ENV`, `NM_CONNECTOR_MODE`, `ANTHROPIC_API_KEY`, `COMPOSIO_API_KEY`, `DEMO_USER_UID`, `AUTH_MODE`,
  `FIREBASE_PROJECT_ID`, `ALLOWED_ORIGINS`, `OPS_ADMIN_EMAILS`, `OPS_SUPPORT_EMAILS`

Deploy flags that matter:

```bash
gcloud run deploy nm-api ... \
  --add-cloudsql-instances PROJECT:REGION:INSTANCE \
  --no-cpu-throttling \
  --max-instances 1
```

`--no-cpu-throttling` keeps CPU allocated between requests, which the worker's long polls need.
`--min-instances 1` keeps an instance alive: Temporal polling is outbound and does not count as traffic, so
without it Cloud Run scales to zero when nobody uses the app and workflows stall.
`--max-instances 1` keeps one worker pool and one API instance within the database connection budget.

Sizing for a Cloud SQL f1-micro (about 25 connections): `NM_DB_POOL_MAX=10`, `NM_WORKER_CONCURRENCY=4`
leaves headroom for migrations, the console and a second revision during a rollout. The pool is shared by
request handlers and activities, so in embedded mode the pool must be strictly larger than the concurrency
(the API logs a warning at startup otherwise). Shutdown fits Cloud Run's 10 s: the worker stops within 8 s at most
(activities get a 5 s grace period) and the pool then closes within 1 s, and a Temporal outage never delays it.

Local runs: unset `TEMPORAL_API_KEY` (and point `TEMPORAL_TARGET` at `127.0.0.1:7243`). The key in `.env` is the
cloud one, and any key now switches on TLS, which the local dev server does not speak.

`GET /v1/ops/runtime/status` (any operator role) reports `{runtime, workspace, database, temporal, worker,
definitionsApplied}` for a quick check; it never returns connection strings or keys. `worker` is `running`,
`stopped` or `not_embedded`. With the runtime off, `database` and `temporal` read `off`. Each check is
bounded (about 3 s) and both run at once, so the route answers within about 4 s during an outage.

## Known limits

- Memory items are not scoped to a tenant: every org reads and writes the same memory spaces.
- Live tool calls are not idempotent across retries: a connector step retried after a timeout may repeat a
  write in the live app (sandbox calls are unaffected).
- A run has no overall deadline; only each human task or approval times out (24 hours by default).
- With Postgres down, real-run endpoints answer 500 rather than 503.
- What a reviewer sees in a human task (order and payment details) is not redacted for PII; do that before
  running on live data.
