import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { HealthView } from "./_components/health-view";

export const metadata: Metadata = { title: "System health" };

export default function HealthPage() {
  return (
    <>
      <PageHeader
        title="System health"
        lede="Service status for the platform and its vendors, and the incidents being worked on."
      />
      <Suspense>
        <HealthView />
      </Suspense>
    </>
  );
}
