import { describe, expect, it } from "vitest";
import {
  budgetChoices,
  budgetLimit,
  capChoices,
  defaultBudget,
  MIN_RUN_BUDGET,
  packRunFee,
  startCap,
} from "./run-budget";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });

describe("run budgets", () => {
  it("offers the usual budgets when nothing limits the run", () => {
    expect(budgetLimit({})).toBeUndefined();
    expect(budgetChoices({})).toEqual([2000, 5000, 10000]);
    expect(defaultBudget({})).toBe(5000);
  });

  it("offers only budgets within the pack's maximum, the maximum among them", () => {
    expect(budgetChoices({ maxBudget: usd(2500) })).toEqual([2000, 2500]);
    expect(defaultBudget({ maxBudget: usd(2500) })).toBe(2500);
    // No usual budget fits a $10 or a $2 maximum: the maximum is the one choice, and the default.
    expect(budgetChoices({ maxBudget: usd(1000) })).toEqual([1000]);
    expect(defaultBudget({ maxBudget: usd(1000) })).toBe(1000);
    expect(budgetChoices({ maxBudget: usd(200) })).toEqual([200]);
    expect(defaultBudget({ maxBudget: usd(200) })).toBe(200);
  });

  it("keeps the per-run cap less the pack's fee as the limit when it is lower", () => {
    expect(budgetLimit({ maxBudget: usd(2500), perRunCap: usd(500) })).toBe(500);
    expect(budgetChoices({ maxBudget: usd(2500), perRunCap: usd(500) })).toEqual([500]);
    const listed = { maxBudget: usd(1000), perRunCap: usd(2000), packFee: usd(1500) };
    expect(budgetLimit(listed)).toBe(500);
    expect(budgetChoices(listed)).toEqual([500]);
    expect(defaultBudget(listed)).toBe(500);
    // A cap with room above the pack's maximum leaves the maximum in charge.
    expect(budgetLimit({ maxBudget: usd(1000), perRunCap: usd(5000), packFee: usd(200) })).toBe(1000);
  });

  it("offers nothing when the fee leaves less than the smallest sensible budget under the cap", () => {
    const tight = { perRunCap: usd(500), packFee: usd(450) };
    expect(budgetLimit(tight)).toBe(50);
    expect(budgetLimit(tight)).toBeLessThan(MIN_RUN_BUDGET);
    expect(budgetChoices(tight)).toEqual([]);
  });

  it("reads the up-front fee from a listing priced per run only", () => {
    expect(packRunFee({ listing: { fee: usd(250), feeUnit: "run" } })).toEqual(usd(250));
    expect(packRunFee({ listing: { fee: usd(30), feeUnit: "call" } })).toBeUndefined();
    expect(packRunFee({ listing: { fee: usd(0), feeUnit: "run" } })).toBeUndefined();
    expect(packRunFee({})).toBeUndefined();
  });

  it("prefers the fee and limit the API gives an added pack, at the version it holds", () => {
    const listing = { fee: usd(400), feeUnit: "run" as const };
    expect(packRunFee({ runFee: usd(250), listing })).toEqual(usd(250));
    expect(packRunFee({ runFee: usd(0), listing })).toBeUndefined();
    const terms = { maxBudget: usd(2500), perRunCap: usd(2000), packFee: usd(400), runBudgetLimit: usd(1750) };
    expect(budgetLimit(terms)).toBe(1750);
    expect(budgetChoices(terms)).toEqual([1750]);
    expect(defaultBudget(terms)).toBe(1750);
  });

  it("offers per-run caps no higher than the pack's maximum and its fee, that ceiling among them", () => {
    expect(capChoices({}, 2000)).toEqual([500, 2000, 5000]);
    expect(capChoices({ maxBudget: usd(1000) }, 2000)).toEqual([500, 1000, 2000]);
    expect(capChoices({ maxBudget: usd(200) }, 2000)).toEqual([200, 2000]);
    expect(capChoices({ maxBudget: usd(1000), packFee: usd(250) }, 2000)).toEqual([500, 1250, 2000]);
    // A cap set before is kept as a choice so the form shows what is saved.
    expect(capChoices({ maxBudget: usd(1000) }, 700)).toEqual([500, 700, 1000]);
    // Even above the ceiling: a saved cap is never quietly dropped.
    expect(capChoices({ maxBudget: usd(1000) }, 5000)).toEqual([500, 1000, 5000]);
    expect(startCap({ maxBudget: usd(1000), perRunCap: usd(5000) })).toBe(5000);
    expect(startCap({ maxBudget: usd(1000) })).toBe(1000);
  });
});
