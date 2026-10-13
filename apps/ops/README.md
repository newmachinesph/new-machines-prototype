# Operator console (`apps/ops`)

The internal command center for New Machines staff: tenants, marketplace review, connectors, the reviewer workforce, runs, guardrails, billing, platform health, the operator team and the audit log. Customers never see it.

Every change an operator makes asks for a reason and is written to the audit log.

## Run it locally

You need the API and the console.

```bash
# 1. API on 8400, dev auth (you are an owner operator, no sign-in)
cd apps/api
AUTH_MODE=dev ALLOWED_ORIGINS=http://localhost:3400 uv run uvicorn app.main:app --port 8400

# 2. Console on 3400
cd apps/ops
cp .env.example .env.local   # then fill it in, see below
pnpm install
pnpm dev
```

Open http://localhost:3400.

### Mock sign-in

Set `NEXT_PUBLIC_AUTH_MOCK=1` in `.env.local` to skip Firebase sign-in and use a fake operator session. The console shows a purple banner while it is on. Mock sign-in is for local work and tests only. `next build` refuses a mock build unless `ALLOW_AUTH_MOCK_BUILD=1`, so it cannot be deployed by accident.

## Environment

### Console (`apps/ops/.env.local`)

| Variable                           | What it is                                         |
| ---------------------------------- | -------------------------------------------------- |
| `NEXT_PUBLIC_API_URL`              | Base URL of the API, e.g. `http://localhost:8400`  |
| `NEXT_PUBLIC_AUTH_MOCK`            | `1` for mock sign-in, otherwise leave empty        |
| `NEXT_PUBLIC_FIREBASE_API_KEY`     | Firebase web config for the project the API trusts |
| `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` | Firebase web config                                |
| `NEXT_PUBLIC_FIREBASE_PROJECT_ID`  | Firebase web config                                |
| `NEXT_PUBLIC_FIREBASE_APP_ID`      | Firebase web config                                |

These are public client values. The build fails if a required one is missing.

### API

| Variable             | What it does                                                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OPS_ADMIN_EMAILS`   | Comma-separated emails with full operator access                                                                                                              |
| `OPS_SUPPORT_EMAILS` | Comma-separated emails with read-only access. Support sees everything; every action is disabled.                                                              |
| `ALLOWED_ORIGINS`    | Comma-separated origins allowed by CORS. Add the console's origin (`http://localhost:3400` locally, the hosted URL in production) next to the customer app's. |
| `AUTH_MODE`          | `dev` skips sign-in and makes every request an owner operator. Never set it in production.                                                                    |

Outside dev mode an operator must sign in with Google or email and password, with a verified email that is on one of the two lists. Anyone else gets "No access".

## Checks

```bash
pnpm typecheck
pnpm lint
pnpm format:check
pnpm test        # unit and component tests (Vitest)
pnpm build
pnpm e2e         # Playwright: builds a mock-auth bundle into .next-e2e, starts the API on 8400 and the console on 3410
```

`pnpm e2e` starts its own API on 8400 and console on 3410, so stop anything already on those ports first.

## Ports

| Port | What                               |
| ---- | ---------------------------------- |
| 3400 | Console, `pnpm dev` / `pnpm start` |
| 3410 | Console under Playwright           |
| 8400 | API for the console                |

## API client

The typed client in `src/lib/api/gen` is generated from `apps/api/openapi.json`:

```bash
pnpm api:gen
```

Regenerate it whenever an `/v1/ops` route changes.

## Runtime pages

These pages read and edit the real runtime (Postgres + Temporal), not the simulated demo data. Start the
API with `NM_RUNTIME=temporal NM_DEFS_AUTO_APPLY=1` (see the root README, "Run the real workflow locally").

| Page           | What it does                                                                                                                                                                          |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/definitions` | Browse and edit the versioned definition files (packs, workflows, agents, connectors, decisions, memory). Validate a draft, then publish it as a new immutable version with a reason. |
| `/agents`      | Each agent definition with its model profile, skills and the tools it may call.                                                                                                       |
| `/contracts`   | Work contracts: inputs, outputs, budgets and approval rules.                                                                                                                          |
| `/memory`      | Review, edit or retire what the runtime has learned and recalls into runs.                                                                                                            |
| `/runs/[id]`   | One real run with its hash-chained work receipt; the chain is verified when the page loads.                                                                                           |

Publishing a definition, editing memory and similar changes ask for a reason and write an audit entry. The
support role is read-only.

## Hosting

The console runs on its own Firebase App Hosting backend, `nm-ops` (asia-southeast1, project `nm-demo-iu7uo4`), at https://nm-ops--nm-demo-iu7uo4.asia-southeast1.hosted.app. Redeploy from this folder:

```bash
npx -y firebase-tools@15.33.0 deploy --only apphosting --project nm-demo-iu7uo4
```

The API it calls (Cloud Run `nm-api`) must:

1. List the console's URL in `ALLOWED_ORIGINS`, next to the customer app's.
2. Set `OPS_ADMIN_EMAILS` (and `OPS_SUPPORT_EMAILS` if needed).

Google sign-in also needs the console's domain in Firebase Authentication's authorized domains.

## Simulated data

The demo environment's tenants, usage, billing and health figures are synthetic. Screens that show simulated data carry a "Simulated" tag.
