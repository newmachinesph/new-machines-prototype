import type { Metadata } from "next";
import { BillingHeader } from "./_components/billing-header";
import { BillingView } from "./_components/billing-view";

export const metadata: Metadata = { title: "Billing" };

export default function BillingPage() {
  return (
    <>
      <BillingHeader />
      <BillingView />
    </>
  );
}
