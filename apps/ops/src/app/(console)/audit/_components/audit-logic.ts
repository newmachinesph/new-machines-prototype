import type { AuditEntry } from "@/lib/api/gen/types.gen";

/** Where a target's page lives in this console. */
export function targetHref(type: AuditEntry["targetType"], id: string): string {
  switch (type) {
    case "tenant":
      return `/tenants/${encodeURIComponent(id)}`;
    case "pack":
      return `/marketplace/${encodeURIComponent(id)}`;
    case "connector":
      return `/connectors?c=${encodeURIComponent(id)}`;
    case "reviewer":
      return "/workforce";
    case "guardrail":
      return "/guardrails";
    case "incident":
      return "/health";
  }
}

/** Client-side free-text filter over summary, reason and actor email. */
export function filterEntries(entries: AuditEntry[], q: string): AuditEntry[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter((e) =>
    [e.summary, e.reason, e.actorEmail].some((field) => field.toLowerCase().includes(needle)),
  );
}
