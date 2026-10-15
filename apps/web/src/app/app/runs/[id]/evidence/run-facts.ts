import type { IntlLocale } from "@/lib/format";
import type { Run } from "@/lib/types";

/** The pack whose deliverable page keeps its written copy; every other pack's page is built from the run. */
export const RECONCILIATION_PACK = "order-payment-reconciliation";

/** An amount the API wrote as "-70.40 USD" (major units, then the currency's code). */
const MONEY_TEXT = /^(-?\d+(?:\.\d+)?) ([A-Z]{3})$/;
/** The currencies the product handles; any other three capitals ("PDF", "CSV") are not money. */
const CURRENCIES = new Set(["USD", "EUR", "GBP", "JPY", "PHP", "INR", "SGD", "AUD", "CAD"]);

/**
 * A deliverable value as the interface writes money ("−$70.40"), when the API sent one in its "70.40 USD"
 * form; any other value as sent. A negative amount takes a minus sign, like the rest of the interface.
 */
export function moneyText(value: string, locale: IntlLocale): string {
  const m = value.match(MONEY_TEXT);
  if (!m || !CURRENCIES.has(m[2])) return value;
  const amount = Number(m[1]);
  const formatted = new Intl.NumberFormat(locale, { style: "currency", currency: m[2] }).format(Math.abs(amount));
  return amount < 0 ? `−${formatted}` : formatted;
}

export type ToolUse = {
  app: string;
  action: string;
  kind: "read" | "write";
  /** Calls that ran (confirmed). */
  ran: number;
  /** Calls that were denied, failed or never ran. */
  notRun: number;
  /** For writes: "granted" when every call ran after a granted approval, "none" when any ran without one. */
  approval: "granted" | "none" | "n/a";
  /** Whether the calls that ran used sandbox data: all of them, some of them or none. */
  sandbox: "all" | "some" | "none";
};

export type Changed = "noCalls" | "nothing" | "simulated" | "afterApproval" | "withoutApproval";

type Call = NonNullable<Run["nodes"][number]["toolCalls"]>[number];

/** The key of a tool use group: one per app and action. */
export const toolKey = (u: { app: string; action: string }) => `${u.app}\u0000${u.action}`;

function isRead(call: Call): boolean {
  if (call.actionClass) return call.actionClass === "read";
  return call.capability.endsWith(".read");
}

/** The run's tool calls grouped by app and action, in the order they first appear. */
export function toolUse(run: Run): ToolUse[] {
  const approved = new Set(run.edges.filter((e) => e.label === "granted" && e.taken).map((e) => e.to));
  const groups = new Map<string, ToolUse & { approvedRuns: number; mockedRuns: number }>();
  for (const node of run.nodes) {
    for (const call of node.toolCalls ?? []) {
      const key = toolKey(call);
      const g = groups.get(key) ?? {
        app: call.app,
        action: call.action,
        kind: isRead(call) ? "read" : "write",
        ran: 0,
        notRun: 0,
        approval: "n/a",
        sandbox: "none",
        approvedRuns: 0,
        mockedRuns: 0,
      };
      if (call.status === "CONFIRMED") {
        g.ran += 1;
        if (approved.has(node.id)) g.approvedRuns += 1;
        if (call.mocked) g.mockedRuns += 1;
      } else {
        g.notRun += 1;
      }
      groups.set(key, g);
    }
  }
  return [...groups.values()].map(({ approvedRuns, mockedRuns, ...g }) => ({
    ...g,
    approval: g.kind === "read" || g.ran === 0 ? "n/a" : approvedRuns === g.ran ? "granted" : "none",
    sandbox: mockedRuns === 0 ? "none" : mockedRuns === g.ran ? "all" : "some",
  }));
}

/** What the run changed outside New Machines, from its tool use. */
export function changed(uses: ToolUse[]): Changed {
  if (uses.length === 0) return "noCalls";
  const writes = uses.filter((u) => u.kind === "write" && u.ran > 0);
  if (writes.length === 0) return "nothing";
  const real = writes.filter((u) => u.sandbox !== "all");
  if (real.length === 0) return "simulated";
  return real.every((u) => u.approval === "granted") ? "afterApproval" : "withoutApproval";
}
