"use client";

import { useMe } from "@/lib/queries/me";

/** Studio writes need the builder role (owner or admin, the API's `require_builder`); members read only. */
export const MANAGERS = new Set(["owner", "admin"]);

export function useCanBuild(): boolean {
  return MANAGERS.has(useMe().data?.role ?? "");
}
