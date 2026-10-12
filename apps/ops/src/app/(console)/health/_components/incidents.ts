import type { Incident } from "@/lib/api/gen/types.gen";

export type IncidentStatus = Incident["status"];
export type Severity = Incident["severity"];

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  investigating: "Investigating",
  monitoring: "Monitoring",
  resolved: "Resolved",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  sev1: "Sev 1, critical",
  sev2: "Sev 2, major",
  sev3: "Sev 3, minor",
};

/** Statuses an update may move an incident to. Never back to an earlier one; resolved is final. */
export function nextStatuses(current: IncidentStatus): IncidentStatus[] {
  switch (current) {
    case "investigating":
      return ["investigating", "monitoring", "resolved"];
    case "monitoring":
      return ["monitoring", "resolved"];
    case "resolved":
      return [];
  }
}

/** Open incidents first (newest first), then resolved ones (newest first). */
export function sortIncidents(list: Incident[]): Incident[] {
  const rank = (i: Incident) => (i.status === "resolved" ? 1 : 0);
  return [...list].sort((a, b) => rank(a) - rank(b) || Date.parse(b.startedAt) - Date.parse(a.startedAt));
}
