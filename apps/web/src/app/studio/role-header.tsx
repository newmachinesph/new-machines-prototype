"use client";

import { PageHeader } from "@/components/ui";
import { useMe } from "@/lib/queries/me";
import { MANAGERS } from "./can-build";

type Copy = { title: string; lede: string };

/**
 * The header of an agent or pack page: a builder edits, a member only looks. The page translates both and this picks
 * one by the role; until /v1/me has answered, the editing copy stands, so a builder's title never changes under them.
 */
export function RoleHeader({ edit, view }: { edit: Copy; view: Copy }) {
  const me = useMe().data;
  const copy = me && !MANAGERS.has(me.role) ? view : edit;
  return <PageHeader title={copy.title} lede={copy.lede} />;
}
