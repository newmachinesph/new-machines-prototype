import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/ui";
import { GuardrailsView } from "./_components/guardrails-view";

export const metadata: Metadata = { title: "Guardrails" };

export default function GuardrailsPage() {
  return (
    <>
      <PageHeader
        title="Guardrails"
        lede="Platform-wide kill switches, feature flags and limits. Every change applies to all tenants and is written to the audit log with your reason."
      />
      <Suspense>
        <GuardrailsView />
      </Suspense>
    </>
  );
}
