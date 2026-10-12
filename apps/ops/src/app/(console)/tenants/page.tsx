import type { Metadata } from "next";
import { Suspense } from "react";
import { TenantsView } from "./_components/tenants-view";

export const metadata: Metadata = { title: "Tenants" };

export default function TenantsPage() {
  return (
    <Suspense>
      <TenantsView />
    </Suspense>
  );
}
