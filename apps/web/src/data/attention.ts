import type { Actor } from "@/lib/types";
import { MEMORY } from "./org";
import { APPROVALS } from "./work";

// The overview's "Needs you" list. Served by GET /v1/organizations/{orgId}/attention.
export type AttentionItem = { actor: Actor; title: string; detail: string; href: string; when: string };

export const ATTENTION: AttentionItem[] = [
  {
    actor: "buyer",
    title: "Approve one outgoing email",
    detail: "Reminder to Cedarline Home, INV-3307, $2,480.00",
    href: "/app/approvals",
    when: APPROVALS[0].requestedAt,
  },
  {
    actor: "policy",
    title: "Refund blocked, specialist assigned",
    detail: "HP-20877, $184.00. Agents may not move money.",
    href: "/app/runs/run_1044",
    when: "2026-10-12T13:18:21Z",
  },
  {
    actor: "machine",
    title: "Check an unconfirmed Drive write",
    detail: "“Reorder list, week 42” may not exist",
    href: "/app/runs/run_1039",
    when: "2026-10-12T13:09:40Z",
  },
  {
    actor: "human",
    title: "Approve a memory from a reviewer",
    detail: MEMORY[0].text,
    href: "/app/memory",
    when: MEMORY[0].createdAt,
  },
];
