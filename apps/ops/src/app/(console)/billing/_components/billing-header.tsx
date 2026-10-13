"use client";

import { LiveSampleNote } from "@/components/live-sample-note";
import { PageHeader, SimTag } from "@/components/ui";
import { useOpsWorkspace } from "@/lib/queries/ops";

const LEDE = "Recurring revenue, AI cost, invoices and reviewer payouts.";

/**
 * The demo tags billing Simulated in its title. The live workspace tags it Sample under the heading instead,
 * and drops the demo's own wording.
 */
export function BillingHeader() {
  const live = useOpsWorkspace() === "live";
  return live ? (
    <PageHeader
      title="Billing"
      lede={`${LEDE} Nothing is charged or paid out.`}
      below={<LiveSampleNote>Billing figures are sample data, not the live workspace&apos;s.</LiveSampleNote>}
    />
  ) : (
    <PageHeader
      title={
        <span className="inline-flex flex-wrap items-center gap-3">
          Billing <SimTag />
        </span>
      }
      lede={`${LEDE} These figures are simulated for the demo; nothing is charged or paid out.`}
    />
  );
}
