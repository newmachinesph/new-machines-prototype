import type { Metadata } from "next";
import { Suspense } from "react";
import { LiveSampleNote } from "@/components/live-sample-note";
import { PageHeader } from "@/components/ui";
import { WorkforceLede, WorkforceView } from "./_components/workforce-view";

export const metadata: Metadata = { title: "Workforce" };

export default function WorkforcePage() {
  return (
    <>
      <PageHeader
        title="Workforce"
        lede={<WorkforceLede />}
        below={<LiveSampleNote>Reviewers here are sample data, not the live workforce.</LiveSampleNote>}
      />
      <Suspense>
        <WorkforceView />
      </Suspense>
    </>
  );
}
