import type { Locator, Page } from "@playwright/test";

/** A route and a locator that only appears once that route's data has rendered. Fixture data stays English in every locale. */
export type RouteSpec = { path: string; ready: (page: Page) => Locator };

const text = (value: string) => (page: Page) => page.locator("main").getByText(value).first();
// For pages that render a phone copy and a desktop copy of the same row, wait for the one that is on screen.
const visibleText = (value: string) => (page: Page) =>
  page.locator("main").getByText(value).filter({ visible: true }).first();
const PACK = text("Order & Payment Reconciliation");
const TASK = text("Correct 3 order-to-payout exceptions");

export const ROUTES: RouteSpec[] = [
  { path: "/", ready: (page) => page.locator("h1").first() },
  { path: "/app", ready: text("Reconcile Oct 11 orders") },
  { path: "/app/runs", ready: visibleText("Reconcile Oct 11 orders") },
  { path: "/app/runs/run_1042", ready: text("Reconcile Oct 1–10 orders") },
  { path: "/app/runs/run_1042/evidence", ready: text("Reconcile Oct 1–10 orders") },
  { path: "/app/runs/new", ready: PACK },
  { path: "/app/marketplace", ready: PACK },
  { path: "/app/marketplace/order-payment-reconciliation", ready: PACK },
  { path: "/app/marketplace/order-payment-reconciliation/install", ready: PACK },
  { path: "/app/agents", ready: text("Finance Agent") },
  { path: "/app/agents/finance-agent", ready: PACK },
  { path: "/app/approvals", ready: text("Send a payment reminder to Cedarline Home") },
  { path: "/app/memory", ready: text("Payout batches post the next business day after the order.") },
  { path: "/app/connections", ready: text("ops@harborandpine.example") },
  { path: "/app/settings", ready: text("Shared demo login") },
  { path: "/app/usage", ready: text("Budget hold for run_1047") },
  { path: "/work", ready: TASK },
  { path: "/work/earnings", ready: TASK },
  { path: "/work/tasks/ht_011", ready: TASK },
];
