import type { ConnectorDefaults, ConnectorEntry } from "@/lib/api/gen/types.gen";

export type Decision = ConnectorDefaults["read"];
export type ActionClass = keyof ConnectorDefaults;

export const ACTION_CLASSES: { key: ActionClass; label: string; hint: string }[] = [
  { key: "read", label: "Read", hint: "Look up data without changing it" },
  { key: "write", label: "Write", hint: "Create or update records" },
  { key: "delete", label: "Delete", hint: "Remove records" },
  { key: "money", label: "Money", hint: "Charge, refund or pay out" },
];

export const DECISION_LABEL: Record<Decision, string> = {
  permit: "Permit",
  require_approval: "Require approval",
  deny: "Deny",
};

export const AUTH_LABEL: Record<ConnectorEntry["authType"], string> = {
  oauth_managed: "OAuth, managed",
  oauth_own_app: "OAuth, own app",
  api_key: "API key",
};

export const STATUS_LABEL: Record<ConnectorEntry["status"], string> = {
  enabled: "Enabled",
  beta: "Beta",
  disabled: "Disabled",
};

/** Error rates at or above this share of calls are shown in the blocked colour. */
export const ERROR_RATE_BLOCKED = 0.05;
export const isHighErrorRate = (rate: number) => rate >= ERROR_RATE_BLOCKED;

export type DefaultsChange = { key: ActionClass; label: string; from: Decision; to: Decision };

/** Which of the four defaults differ, in display order. */
export function diffDefaults(before: ConnectorDefaults, after: ConnectorDefaults): DefaultsChange[] {
  return ACTION_CLASSES.filter((a) => before[a.key] !== after[a.key]).map((a) => ({
    key: a.key,
    label: a.label,
    from: before[a.key],
    to: after[a.key],
  }));
}

/** "Delete: deny to require approval. Money: deny to permit." */
export function describeChanges(changes: DefaultsChange[]): string {
  return changes
    .map((c) => `${c.label}: ${DECISION_LABEL[c.from].toLowerCase()} to ${DECISION_LABEL[c.to].toLowerCase()}.`)
    .join(" ");
}
