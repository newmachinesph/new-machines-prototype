import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { RunsView } from "./_components/runs-view";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <>
      <PageHeader
        title="Runs"
        lede="Workflow runs across all tenants. This view is read-only: open a tenant to act on its account."
      />
      <Suspense>
        <RunsView />
      </Suspense>
    </>
  );
}
