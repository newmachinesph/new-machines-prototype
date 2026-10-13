"use client";

import type { ReactNode } from "react";
import { useOpsWorkspace } from "@/lib/queries/ops";
import { SampleTag } from "./ui";

/**
 * For pages still backed by fixtures: in the live workspace, says so with a Sample tag. Pass it to `PageHeader`
 * as `below`, so it sits under the page heading. Renders nothing in the demo workspace, whose fixtures are the
 * product.
 */
export function LiveSampleNote({ children }: { children: ReactNode }) {
  if (useOpsWorkspace() !== "live") return null;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
      <SampleTag />
      {children}
    </p>
  );
}
