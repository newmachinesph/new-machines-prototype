import type { Metadata } from "next";
import { PageHeader, SimTag } from "@/components/ui";
import { BillingView } from "./_components/billing-view";

export const metadata: Metadata = { title: "Billing" };

export default function BillingPage() {
  return (
    <>
      <PageHeader
        title={
          <span className="inline-flex flex-wrap items-center gap-3">
            Billing <SimTag />
          </span>
        }
        lede="Recurring revenue, AI cost, invoices and reviewer payouts. These figures are simulated for the demo; nothing is charged or paid out."
      />
      <BillingView />
    </>
  );
}
