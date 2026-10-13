import type { Metadata } from "next";
import { Suspense } from "react";
import { LiveSampleNote } from "@/components/live-sample-note";
import { PageHeader } from "@/components/ui";
import { HealthView } from "./_components/health-view";

export const metadata: Metadata = { title: "System health" };

export default function HealthPage() {
  return (
    <>
      <PageHeader
        title="System health"
        lede="Service status for the platform and its vendors, and the incidents being worked on."
        below={<LiveSampleNote>Service status and incidents here are sample data, not monitored live.</LiveSampleNote>}
      />
      <Suspense>
        <HealthView />
      </Suspense>
    </>
  );
}
