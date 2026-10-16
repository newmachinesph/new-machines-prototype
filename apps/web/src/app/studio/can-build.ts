"use client";

import { useMe } from "@/lib/queries/me";
import { isManager } from "@/lib/roles";

export { MANAGERS } from "@/lib/roles";

/** Studio writes and publishing need the builder role (owner or admin, the API's `require_builder`); members
 * read the Studio only. */
export function useCanBuild(): boolean {
  return isManager(useMe().data?.role);
}
