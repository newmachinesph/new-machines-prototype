import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { WorkforceView } from "./_components/workforce-view";

export const metadata: Metadata = { title: "Workforce" };

export default function WorkforcePage() {
  return (
    <>
      <PageHeader
        title="Workforce"
        lede="Human reviewers who take on tasks when a run needs a person. Approve applicants, set levels, and pause anyone who should stop receiving work."
      />
      <Suspense>
        <WorkforceView />
      </Suspense>
    </>
  );
}
