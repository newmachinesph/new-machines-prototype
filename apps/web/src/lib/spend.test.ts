import { describe, expect, it } from "vitest";
import { daysLeftInMonth, monthOf, spendSplit } from "./spend";
import type { LedgerTxn, Organization } from "./types";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const org = (spent: number): Organization => ({
  id: "org_x",
  name: "Org",
  short: "Org",
  plan: "Pro",
  monthlyCap: usd(25000),
  monthSpent: usd(spent),
  region: "us-central1",
});
const txn = (over: Partial<LedgerTxn>): LedgerTxn => ({
  id: "t",
  at: "2026-10-05T10:00:00Z",
  kind: "ai_usage",
  description: "",
  amount: usd(0),
  status: "POSTED",
  lines: [],
  ...over,
});

describe("spendSplit", () => {
  it("splits the demo ledger the way the overview always showed it", () => {
    const ledger = [
      txn({ kind: "hold", status: "HELD", amount: usd(5000), runId: "run_1047" }),
      txn({ kind: "ai_usage", status: "ELIGIBLE", amount: usd(190) }),
      txn({
        kind: "human_pay",
        status: "ELIGIBLE",
        amount: usd(750),
        lines: [{ account: "Buyer charges", debit: 750 }],
      }),
      txn({
        kind: "human_pay",
        amount: usd(400),
        lines: [{ account: "Platform absorbed cost", debit: 400 }],
      }),
      txn({ kind: "plan", amount: usd(4900) }),
    ];
    const split = spendSplit(org(6194), ledger, "2026-10");
    expect(split.plan.amountMinor).toBe(4900);
    expect(split.reviewers.amountMinor).toBe(750);
    expect(split.agents.amountMinor).toBe(544);
    expect(split.reviewerPayTotal.amountMinor).toBe(1150);
    expect(split.reviewerPayments).toBe(2);
    expect(split.absorbed.amountMinor).toBe(400);
    expect(split.held.amountMinor).toBe(5000);
    expect(split.heldRuns).toEqual(["run_1047"]);
  });

  it("reads a live run's spent breakdown and skips other months", () => {
    const spent = { ai: usd(120), tools: usd(30), human: usd(300) };
    const ledger = [
      txn({ kind: "run", amount: usd(450), spent }),
      txn({ kind: "run", at: "2026-09-30T23:00:00Z", amount: usd(999), spent: { ...spent, human: usd(999) } }),
    ];
    const split = spendSplit(org(450), ledger, "2026-10");
    expect(split.plan.amountMinor).toBe(0);
    expect(split.reviewers.amountMinor).toBe(300);
    expect(split.agents.amountMinor).toBe(150);
    expect(split.reviewerPayments).toBe(1);
    expect(split.held.amountMinor).toBe(0);
  });

  it("sums the month's publisher fees, which the agents figure includes", () => {
    const fee = (amount: number) => ({
      listingId: "lst_1",
      name: "Tax filing",
      publisher: "Harbor Cafe",
      kind: "pack_run" as const,
      quantity: 1,
      unit: usd(amount),
      amount: usd(amount),
    });
    const spent = { ai: usd(100), tools: usd(0), human: usd(0) };
    const ledger = [
      txn({ kind: "run", amount: usd(350), spent, fees: [fee(250)] }),
      txn({ kind: "run", at: "2026-09-30T23:00:00Z", amount: usd(999), spent, fees: [fee(999)] }),
    ];
    const split = spendSplit(org(350), ledger, "2026-10");
    expect(split.fees.amountMinor).toBe(250);
    expect(split.agents.amountMinor).toBe(350);
    expect(split.agentsExclFees.amountMinor).toBe(100);
  });

  it("never lets the agents figure without fees go below zero", () => {
    const fee = {
      listingId: "l",
      name: "T",
      publisher: "H",
      kind: "pack_run" as const,
      quantity: 1,
      unit: usd(900),
      amount: usd(900),
    };
    const split = spendSplit(org(100), [txn({ kind: "run", amount: usd(100), fees: [fee] })], "2026-10");
    expect(split.agentsExclFees.amountMinor).toBe(0);
  });

  it("is all zero for a new workspace", () => {
    const split = spendSplit(org(0), [], "2026-10");
    expect([split.plan, split.agents, split.reviewers, split.held, split.fees].map((m) => m.amountMinor)).toEqual([
      0, 0, 0, 0, 0,
    ]);
  });
});

describe("billing month", () => {
  it("counts the days left after today", () => {
    expect(daysLeftInMonth(new Date("2026-10-12T16:40:00Z"))).toBe(19);
    expect(daysLeftInMonth(new Date("2026-02-28T00:00:00Z"))).toBe(0);
  });
  it("names the UTC month", () => {
    expect(monthOf(new Date("2026-10-31T23:59:00Z"))).toBe("2026-10");
  });
});
