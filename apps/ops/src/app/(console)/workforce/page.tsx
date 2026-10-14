import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { WorkforceLede, WorkforceView } from "./_components/workforce-view";

export const metadata: Metadata = { title: "Workforce" };

export default function WorkforcePage() {
  return (
    <>
      <PageHeader title="Workforce" lede={<WorkforceLede />} />
      <Suspense>
        <WorkforceView />
      </Suspense>
    </>
  );
}
