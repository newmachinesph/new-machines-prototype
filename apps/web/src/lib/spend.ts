import { usd } from "./format";
import type { LedgerTxn, Money, Organization } from "./types";

/** The ledger account a charge to the buyer is debited to. Reviewer pay debited elsewhere was absorbed. */
const BUYER_CHARGES = "Buyer charges";

/** Where this month's spend went, and what is held or absorbed, from the org and its ledger. */
export type SpendSplit = {
  /** The month's plan fee (none on a trial). */
  plan: Money;
  /** Agents, models and tools: the month's spend less the plan and the reviewer pay the buyer paid. It includes
   * the publisher fees (`fees`). */
  agents: Money;
  /** `agents` without the publisher fees, which are shown as their own line wherever the split is shown. */
  agentsExclFees: Money;
  /** Publisher fees charged this month (simulated). */
  fees: Money;
  /** Reviewer pay charged to the buyer this month. */
  reviewers: Money;
  /** All reviewer pay this month, including what New Machines absorbed. */
  reviewerPayTotal: Money;
  /** How many reviewer payments make up `reviewerPayTotal`. */
  reviewerPayments: number;
  /** Reviewer pay New Machines absorbed (for example after a failed verification). */
  absorbed: Money;
  /** Budget held for runs in progress, and those runs. */
  held: Money;
  heldRuns: string[];
};

/** "YYYY-MM" of a moment, in UTC (billing months are UTC). */
export const monthOf = (at: Date) => at.toISOString().slice(0, 7);

/**
 * Splits the month's spend. Runs carry their own `spent` breakdown; older ledger kinds (plan, reviewer
 * pay, holds) are read from the transaction itself. Only the billing month's entries count.
 */
export function spendSplit(org: Organization, ledger: LedgerTxn[], month: string): SpendSplit {
  let plan = 0;
  let reviewers = 0;
  let reviewerPayTotal = 0;
  let reviewerPayments = 0;
  let absorbed = 0;
  let held = 0;
  let fees = 0;
  const heldRuns: string[] = [];
  for (const txn of ledger) {
    if (!txn.at.startsWith(month)) continue;
    const amount = txn.amount.amountMinor;
    if (txn.kind === "plan") plan += amount;
    if (txn.kind === "human_pay") {
      reviewerPayments += 1;
      reviewerPayTotal += amount;
      if (txn.lines.some((l) => l.account === BUYER_CHARGES && l.debit)) reviewers += amount;
      else absorbed += amount;
    }
    for (const f of txn.fees ?? []) fees += f.amount.amountMinor;
    const human = txn.spent?.human.amountMinor ?? 0;
    if (human > 0) {
      reviewerPayments += 1;
      reviewerPayTotal += human;
      reviewers += human;
    }
    if (txn.status === "HELD") {
      held += amount;
      if (txn.runId) heldRuns.push(txn.runId);
    }
  }
  const agents = Math.max(0, org.monthSpent.amountMinor - plan - reviewers);
  return {
    plan: usd(plan),
    agents: usd(agents),
    agentsExclFees: usd(Math.max(0, agents - fees)),
    fees: usd(fees),
    reviewers: usd(reviewers),
    reviewerPayTotal: usd(reviewerPayTotal),
    reviewerPayments,
    absorbed: usd(absorbed),
    held: usd(held),
    heldRuns,
  };
}

/** Whole days left in `at`'s UTC month, not counting today. */
export function daysLeftInMonth(at: Date): number {
  const last = new Date(Date.UTC(at.getUTCFullYear(), at.getUTCMonth() + 1, 0)).getUTCDate();
  return last - at.getUTCDate();
}
