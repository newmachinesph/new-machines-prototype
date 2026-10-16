/**
 * What a run of a pack may be given, as the API checks it at the start: at most the pack's maximum
 * (422 BUDGET_TOO_HIGH), and the budget with the pack's per-run fee paid up front within the per-run cap set
 * when the pack was added (409 RUN_BUDGET_OVER_CAP). Pure: no React.
 */
import type { MarketplaceListing } from "@/lib/api/gen/types.gen";
import type { Money } from "./types";

/** The usual budgets the start form offers, and the one it starts at, in minor units. */
const BUDGETS = [2000, 5000, 10000] as const;
const DEFAULT_BUDGET = 5000;
/** The smallest budget worth starting a run with ($1, the least a pack may set as its maximum). */
export const MIN_RUN_BUDGET = 100;
/** The usual per-run caps offered when a pack is added, and the one it starts at. */
const CAPS = [500, 2000, 5000] as const;
const DEFAULT_CAP = 2000;

export type BudgetTerms = {
  /** The pack's maximum budget per run (its Work Contract's). */
  maxBudget?: Money;
  /** The per-run spending cap chosen when the pack was added. */
  perRunCap?: Money;
  /** Another workspace's per-run fee for the pack, paid up front within the per-run cap. */
  packFee?: Money;
  /** An added pack's limit as the API works it out, at the fee of the version the workspace holds. */
  runBudgetLimit?: Money;
};

/** A pack's fee per run, paid up front: an added pack's at the version it holds (`runFee`), else the listing's
 * current one; undefined for a pack without one (or priced per call). */
export function packRunFee(pack: {
  runFee?: Money;
  listing?: Pick<MarketplaceListing, "fee" | "feeUnit">;
}): Money | undefined {
  if (pack.runFee) return pack.runFee.amountMinor > 0 ? pack.runFee : undefined;
  const listing = pack.listing;
  return listing && listing.feeUnit === "run" && listing.fee.amountMinor > 0 ? listing.fee : undefined;
}

/** The most a run may be given: the API's limit for an added pack, else the pack's maximum and the per-run cap
 * less the pack's fee. Undefined: no limit. */
export function budgetLimit(terms: BudgetTerms): number | undefined {
  if (terms.runBudgetLimit) return terms.runBudgetLimit.amountMinor;
  const limits: number[] = [];
  if (terms.maxBudget) limits.push(terms.maxBudget.amountMinor);
  if (terms.perRunCap) limits.push(terms.perRunCap.amountMinor - (terms.packFee?.amountMinor ?? 0));
  return limits.length ? Math.min(...limits) : undefined;
}

/** The budgets to offer: the usual ones within the limit, and the limit itself. None when the limit is below the
 * smallest sensible budget (the form then says why). */
export function budgetChoices(terms: BudgetTerms): number[] {
  const limit = budgetLimit(terms);
  if (limit === undefined) return [...BUDGETS];
  if (limit < MIN_RUN_BUDGET) return [];
  return [...BUDGETS.filter((b) => b < limit), limit];
}

/** The budget a run starts with: the usual one, lowered to the limit (so the maximum when no usual budget fits). */
export function defaultBudget(terms: BudgetTerms): number {
  const limit = budgetLimit(terms);
  return limit === undefined ? DEFAULT_BUDGET : Math.min(DEFAULT_BUDGET, limit);
}

/** The highest per-run cap worth setting: the pack's maximum budget with its fee on top. Undefined: no limit. */
export const capCeiling = (terms: BudgetTerms) =>
  terms.maxBudget ? terms.maxBudget.amountMinor + (terms.packFee?.amountMinor ?? 0) : undefined;

/** The per-run cap the form starts at: the one saved, even above the ceiling (so saving other settings keeps
 * it), else the usual one, never above the ceiling. */
export function startCap(terms: BudgetTerms): number {
  if (terms.perRunCap) return terms.perRunCap.amountMinor;
  const ceiling = capCeiling(terms);
  return ceiling === undefined ? DEFAULT_CAP : Math.min(DEFAULT_CAP, ceiling);
}

/** The per-run caps to offer: the usual ones up to the ceiling, the ceiling itself, and `current` (even above
 * the ceiling, so a saved cap is never dropped), in order. */
export function capChoices(terms: BudgetTerms, current: number): number[] {
  const ceiling = capCeiling(terms);
  const usual = ceiling === undefined ? [...CAPS] : [...CAPS.filter((c) => c < ceiling), ceiling];
  return [...new Set([...usual, current])].sort((a, b) => a - b);
}
