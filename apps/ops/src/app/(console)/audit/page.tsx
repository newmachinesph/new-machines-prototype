import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { AuditView } from "./_components/audit-view";

export const metadata: Metadata = { title: "Audit log" };

export default function AuditPage() {
  return (
    <>
      <PageHeader title="Audit log" lede="Every change made in this console, newest first, with who made it and why." />
      <Suspense>
        <AuditView />
      </Suspense>
    </>
  );
}
