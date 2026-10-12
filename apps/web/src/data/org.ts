import type { Connection, LedgerTxn, MemoryItem } from "@/lib/types";
import { usd } from "@/lib/format";

export const ORG = {
  id: "org_hp01",
  name: "Harbor & Pine Supply Co.",
  short: "Harbor & Pine",
  plan: "Pro",
  monthlyCap: usd(25000),
  monthSpent: usd(6194),
  region: "us-central1",
};

export const CONNECTIONS: Connection[] = [
  {
    app: "Google Sheets",
    account: "ops@harborandpine.example",
    status: "connected",
    provider: "Composio",
    oauthScopes: ["spreadsheets.readonly"],
    grants: [
      { install: "Order & Payment Reconciliation", capability: "orders.read, payment.read", access: "read" },
      { install: "Overdue Invoice Follow-up", capability: "invoice.read", access: "read" },
      { install: "Weekly Inventory Report", capability: "inventory.read", access: "read" },
    ],
    lastUsed: "2026-10-12T16:05:24Z",
    health: "Healthy",
  },
  {
    app: "Gmail",
    account: "accounts@harborandpine.example",
    status: "connected",
    provider: "Composio",
    oauthScopes: ["gmail.readonly", "gmail.send"],
    grants: [
      { install: "Overdue Invoice Follow-up", capability: "message.send", access: "write (approval)" },
      { install: "Refund Triage", capability: "message.read", access: "read" },
    ],
    lastUsed: "2026-10-12T13:17:40Z",
    health: "Healthy",
  },
  {
    app: "Google Drive",
    account: "ops@harborandpine.example",
    status: "connected",
    provider: "Composio",
    oauthScopes: ["drive.file"],
    grants: [
      {
        install: "Weekly Inventory Report",
        capability: "drive.file.create (Ops / Weekly reports)",
        access: "write (approval)",
      },
      { install: "Order & Payment Reconciliation", capability: "drive.file.create", access: "write (approval)" },
    ],
    lastUsed: "2026-10-12T13:09:31Z",
    health: "1 write unconfirmed",
  },
  {
    app: "Slack",
    account: "",
    status: "not_connected",
    provider: "Composio",
    oauthScopes: [],
    grants: [],
  },
  {
    app: "Shopify",
    account: "harbor-and-pine (sandbox)",
    status: "sandbox",
    provider: "Mock",
    oauthScopes: ["read_orders", "write_orders"],
    grants: [
      { install: "Refund Triage", capability: "orders.read", access: "read" },
      { install: "Refund Triage", capability: "refund.issue", access: "denied" },
    ],
    lastUsed: "2026-10-12T13:17:44Z",
    health: "Mock data, no live effects",
  },
  {
    app: "Stripe",
    account: "acct_test_hp (sandbox)",
    status: "sandbox",
    provider: "Mock",
    oauthScopes: ["read_only"],
    grants: [],
    health: "Mock data, no live effects",
  },
];

export const MEMORY: MemoryItem[] = [
  {
    id: "mem_221",
    text: "Stripe pays out weekend orders on Tuesday. Treat a missing Monday payout for a Saturday or Sunday order as pending, not missing.",
    scope: "Agent installation",
    scopeName: "Finance Agent in Order & Payment Reconciliation",
    state: "CANDIDATE",
    source: "Reviewer 204's correction on task ht_009",
    sourceRun: "run_1042",
    proposedBy: "Memory step",
    createdAt: "2026-10-11T14:39:31Z",
    conflictsWith: "mem_212",
  },
  {
    id: "mem_212",
    text: "Payout batches post the next business day after the order.",
    scope: "Organization",
    scopeName: "Harbor & Pine",
    state: "APPROVED",
    source: "Finance onboarding notes, Sep 2",
    proposedBy: "You",
    createdAt: "2026-09-02T17:00:00Z",
    usedIn: 9,
  },
  {
    id: "mem_219",
    text: "A difference of $1.50 or less on a Shopify Payments order is the processing fee, not a mismatch.",
    scope: "Agent installation",
    scopeName: "Finance Agent in Order & Payment Reconciliation",
    state: "APPROVED",
    source: "Reviewer 204's correction on task ht_006",
    sourceRun: "run_1031",
    proposedBy: "Memory step",
    createdAt: "2026-09-21T15:31:00Z",
    usedIn: 3,
  },
  {
    id: "mem_215",
    text: "Cedarline Home pays by ACH about 5 business days after a reminder.",
    scope: "Organization",
    scopeName: "Harbor & Pine",
    state: "APPROVED",
    source: "Gmail thread with Cedarline Home, Sep 18",
    proposedBy: "Finance Agent",
    createdAt: "2026-09-18T20:10:00Z",
    usedIn: 2,
  },
  {
    id: "mem_208",
    text: "Ignore orders under $5 when reconciling.",
    scope: "Agent installation",
    scopeName: "Finance Agent in Order & Payment Reconciliation",
    state: "REJECTED",
    source: "Finance Agent suggestion, run_1027",
    proposedBy: "Finance Agent",
    createdAt: "2026-09-14T15:00:00Z",
  },
];

export const LEDGER: LedgerTxn[] = [
  {
    id: "txn_5512",
    at: "2026-10-12T16:05:12Z",
    kind: "hold",
    description: "Budget hold for run_1047",
    runId: "run_1047",
    amount: usd(5000),
    status: "HELD",
    lines: [
      { account: "Buyer available budget", debit: 5000 },
      { account: "Run holds", credit: 5000 },
    ],
  },
  {
    id: "txn_5498",
    at: "2026-10-11T16:12:31Z",
    kind: "ai_usage",
    description: "Agent and model usage, run_1042",
    runId: "run_1042",
    amount: usd(190),
    status: "ELIGIBLE",
    lines: [
      { account: "Buyer charges", debit: 190 },
      { account: "Platform revenue: usage", credit: 190 },
    ],
  },
  {
    id: "txn_5497",
    at: "2026-10-11T16:12:31Z",
    kind: "human_pay",
    description: "Reviewer pay, task ht_009",
    runId: "run_1042",
    amount: usd(750),
    status: "ELIGIBLE",
    lines: [
      { account: "Buyer charges", debit: 750 },
      { account: "Worker payable: Reviewer 204", credit: 750 },
    ],
  },
  {
    id: "txn_5460",
    at: "2026-10-05T16:02:00Z",
    kind: "ai_usage",
    description: "Agent and model usage, run_1028",
    runId: "run_1028",
    amount: usd(43),
    status: "POSTED",
    lines: [
      { account: "Buyer charges", debit: 43 },
      { account: "Platform revenue: usage", credit: 43 },
    ],
  },
  {
    id: "txn_5421",
    at: "2026-10-01T15:58:21Z",
    kind: "refund",
    description: "Hold released, run_1036 failed verification",
    runId: "run_1036",
    amount: usd(-117),
    status: "POSTED",
    lines: [
      { account: "Run holds", debit: 117 },
      { account: "Buyer available budget", credit: 117 },
    ],
  },
  {
    id: "txn_5420",
    at: "2026-10-01T15:57:41Z",
    kind: "human_pay",
    description: "Reviewer pay, task ht_010 (owed even though the run failed)",
    runId: "run_1036",
    amount: usd(400),
    status: "POSTED",
    lines: [
      { account: "Platform absorbed cost", debit: 400 },
      { account: "Worker payable: Reviewer 204", credit: 400 },
    ],
  },
  {
    id: "txn_5400",
    at: "2026-10-01T00:00:00Z",
    kind: "plan",
    description: "Pro plan, October",
    amount: usd(4900),
    status: "POSTED",
    lines: [
      { account: "Buyer charges", debit: 4900 },
      { account: "Platform revenue: subscription", credit: 4900 },
    ],
  },
];

export const MCP_TOKENS = [
  {
    id: "pat_07",
    name: "model Desktop",
    last4: "7Q2K",
    scopes: ["agents:read", "runs:read", "runs:start", "approvals:list"],
    createdAt: "2026-10-10T18:00:00Z",
    expiresAt: "2026-11-09T18:00:00Z",
    lastUsed: "2026-10-12T15:58:00Z",
  },
];

export const POLICIES = [
  {
    ref: "tool_actions@3",
    summary: "Reads are permitted. Writes need your approval. Deleting data is denied.",
    updated: "Oct 2",
  },
  {
    ref: "refunds@2",
    summary: "Agents can propose refunds but never issue one. A refunds specialist issues them.",
    updated: "Sep 30",
  },
  {
    ref: "human_review@4",
    summary: "Any payment mismatch must be reviewed by a person before acceptance.",
    updated: "Sep 28",
  },
  {
    ref: "region_us@1",
    summary: "Customer data is processed in us-central1. Reviewers may be in the US or the Philippines.",
    updated: "Sep 12",
  },
];

export const MEMBERS = [
  { name: "Demo operator", email: "Shared demo login", role: "Owner", via: "Email and password" },
  { name: "Reviewer guest", email: "Any Google account", role: "Member", via: "Google" },
];
