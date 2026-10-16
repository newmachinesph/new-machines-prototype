import type { Money } from "@/lib/api/gen/types.gen";
import { money } from "@/lib/format";
import type { ListingStatusFilter } from "@/lib/queries/listings";

type Kind = "pack" | "agent";

/** A price with its unit: a pack is charged per run, an agent per call. Zero is "No fee". */
export function priceText(m: Money, kind: Kind): string {
  if (m.amountMinor <= 0) return "No fee";
  return `${money(m)} ${kind === "pack" ? "per run" : "per call"}`;
}

/**
 * The price an operator should see in the queue. `price` holds the approved version's price and is 0 until
 * a first approval, so a pending listing shows the waiting version's price instead.
 */
export function queuePrice(l: { status: string; price: Money; pending?: { price: Money } }): Money {
  return l.status === "pending" && l.pending ? l.pending.price : l.price;
}

export const TABS = ["in_review", "listed", "unlisted", "pending", "all"] as const;
export type Tab = (typeof TABS)[number];

export const TAB_LABEL: Record<Tab, string> = {
  in_review: "In review",
  listed: "Listed",
  unlisted: "Unlisted",
  pending: "Pending",
  all: "All",
};

export const TAB_EMPTY: Record<Tab, string> = {
  in_review: "Nothing waiting for review.",
  listed: "Nothing is listed yet.",
  unlisted: "Nothing is unlisted.",
  pending: "Nothing is pending.",
  all: "No listings yet.",
};

export const tabStatus = (tab: Tab): ListingStatusFilter | undefined => (tab === "all" ? undefined : tab);

export const STATUS_LABEL = { pending: "Pending", listed: "Listed", unlisted: "Unlisted" } as const;

export const HISTORY_ACTION: Record<string, string> = {
  approve: "Approved",
  approved: "Approved",
  request_changes: "Requested changes",
  reject: "Rejected",
  rejected: "Rejected",
  unlist: "Unlisted",
  relist: "Relisted",
  submit: "Submitted for review",
};

/** An audit action in words; unknown actions fall back to sentence-cased text. */
export function historyAction(action: string): string {
  const known = HISTORY_ACTION[action];
  if (known) return known;
  const words = action.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
