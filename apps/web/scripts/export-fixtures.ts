// Writes the demo data in src/data to apps/api/app/fixtures as JSON. src/data stays the single
// place demo data is edited; run `pnpm fixtures:export` after changing it.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  AGENTS,
  APPROVALS,
  ATTENTION,
  CONNECTIONS,
  EARNINGS,
  HUMAN_TASKS,
  LEDGER,
  MCP_TOKENS,
  MEMBERS,
  MEMORY,
  ORG,
  PACKS,
  POLICIES,
  RUNS,
  TASK_BUYER,
} from "../src/data";
import { OLDER_RUNS } from "../src/data/runs-other";

const out = join(dirname(fileURLToPath(import.meta.url)), "../../api/app/fixtures");
mkdirSync(out, { recursive: true });
const write = (name: string, value: unknown) =>
  writeFileSync(join(out, `${name}.json`), `${JSON.stringify(value, null, 2)}\n`);

write("agents", AGENTS);
write("packs", PACKS);
write("runs", RUNS);
write("older_runs", OLDER_RUNS);
write(
  "human_tasks",
  HUMAN_TASKS.map((t) => ({ ...t, buyer: TASK_BUYER[t.id] ?? "A business customer" })),
);
write("approvals", APPROVALS);
write("connections", CONNECTIONS);
write("memory", MEMORY);
write("ledger", LEDGER);
write("earnings", EARNINGS);
write("tokens", MCP_TOKENS);
write("members", MEMBERS);
write("policies", POLICIES);
write("org", ORG);
write("attention", ATTENTION);
console.log(`Wrote fixtures to ${out}`);
