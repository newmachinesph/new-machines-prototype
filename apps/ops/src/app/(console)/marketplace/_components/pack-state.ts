import type { PackAction } from "@/lib/queries/marketplace";

export type PackStatus = "draft" | "in_review" | "published" | "deprecated" | "rejected";

export const TABS = ["in_review", "published", "drafts", "retired"] as const;
export type Tab = (typeof TABS)[number];

export const TAB_LABEL: Record<Tab, string> = {
  in_review: "In review",
  published: "Published",
  drafts: "Drafts",
  retired: "Deprecated and rejected",
};

export const TAB_EMPTY: Record<Tab, string> = {
  in_review: "No packs waiting for review.",
  published: "No packs are published yet. Approve one from the In review tab.",
  drafts: "No drafts. Use New pack to start one.",
  retired: "No deprecated or rejected packs.",
};

export const STATUS_LABEL: Record<PackStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  published: "Published",
  deprecated: "Deprecated",
  rejected: "Rejected",
};

export function tabFor(status: PackStatus): Tab {
  if (status === "draft") return "drafts";
  if (status === "deprecated" || status === "rejected") return "retired";
  return status;
}

export function tabCounts(packs: { status: PackStatus }[]): Record<Tab, number> {
  const counts: Record<Tab, number> = { in_review: 0, published: 0, drafts: 0, retired: 0 };
  for (const p of packs) counts[tabFor(p.status)] += 1;
  return counts;
}

/** In review when anything is waiting, otherwise Published. */
export function defaultTab(packs: { status: PackStatus }[]): Tab {
  return packs.some((p) => p.status === "in_review") ? "in_review" : "published";
}

/** The state machine's valid moves from a status. The API rejects the rest with 409 INVALID_TRANSITION. */
export function validActions(status: PackStatus, certified: boolean): PackAction[] {
  switch (status) {
    case "draft":
    case "rejected":
      return ["submit"];
    case "in_review":
      return ["approve", "reject"];
    case "published":
      return certified ? ["deprecate"] : ["certify", "deprecate"];
    case "deprecated":
      return ["republish"];
  }
}

/** A kebab-case slug from a display name: "Invoice Matching (EU)" becomes "invoice-matching-eu". */
export function slugify(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;
