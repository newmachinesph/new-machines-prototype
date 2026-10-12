import type { Reviewer } from "@/lib/api/gen/types.gen";

export const TABS = ["applicants", "active", "suspended"] as const;
export type Tab = (typeof TABS)[number];

export const TAB_STATUS: Record<Tab, Reviewer["status"]> = {
  applicants: "applicant",
  active: "active",
  suspended: "suspended",
};

export const LEVELS: Reviewer["level"][] = ["trainee", "qualified", "senior"];

export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function countByTab(reviewers: Reviewer[]): Record<Tab, number> {
  return {
    applicants: reviewers.filter((r) => r.status === "applicant").length,
    active: reviewers.filter((r) => r.status === "active").length,
    suspended: reviewers.filter((r) => r.status === "suspended").length,
  };
}

/** The URL's tab wins; otherwise applicants when anyone is waiting, else active. */
export function resolveTab(requested: Tab | null, counts: Record<Tab, number>): Tab {
  if (requested) return requested;
  return counts.applicants > 0 ? "applicants" : "active";
}

/** The level dialog only confirms a real change. */
export const canSetLevel = (current: Reviewer["level"], next: Reviewer["level"]) => current !== next;
