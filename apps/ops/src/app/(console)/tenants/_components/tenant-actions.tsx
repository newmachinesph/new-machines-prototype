"use client";

import { useState } from "react";
import { focusPageHeading, Select, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button } from "@/components/ui";
import type { TenantDetail } from "@/lib/api/gen/types.gen";
import { money } from "@/lib/format";
import { DOLLARS_HINT, minorToDollarsInput, parseDollarsToMinor } from "@/lib/money";
import { useCanWrite, useOpsWorkspace } from "@/lib/queries/ops";
import { useReactivateTenant, useSetTenantPlan, useSetTenantSpendCap, useSuspendTenant } from "@/lib/queries/tenants";

const PLANS = ["Starter", "Pro", "Enterprise"] as const;
type Plan = (typeof PLANS)[number];
type Dialog = "plan" | "cap" | "suspend" | "reactivate" | null;

export function TenantActions({ tenant }: { tenant: TenantDetail }) {
  const canWrite = useCanWrite();
  const live = useOpsWorkspace() === "live";
  // The live workspace cannot change a plan yet (the API answers 409), so it offers no Change plan.
  const canChangePlan = !live;
  const toast = useToast();
  const suspend = useSuspendTenant();
  const reactivate = useReactivateTenant();
  const setPlan = useSetTenantPlan();
  const setCap = useSetTenantSpendCap();
  const [open, setOpen] = useState<Dialog>(null);
  const [plan, setPlanValue] = useState<Plan>(tenant.plan);
  const [capDollars, setCapDollars] = useState(minorToDollarsInput(tenant.monthlyCap.amountMinor));

  const path = { tenant_id: tenant.id };
  const openDialog = (d: Exclude<Dialog, null>) => {
    // Start each dialog from the current values so an unchanged value is detectable.
    setPlanValue(tenant.plan);
    setCapDollars(minorToDollarsInput(tenant.monthlyCap.amountMinor));
    setOpen(d);
  };
  const onOpenChange = (d: Exclude<Dialog, null>) => (o: boolean) => setOpen(o ? d : null);

  const capMinor = parseDollarsToMinor(capDollars);
  const capUnchanged = capMinor === tenant.monthlyCap.amountMinor;
  const canSuspend = tenant.status === "active" || tenant.status === "trial";
  const canReactivate = tenant.status === "suspended";
  const churned = tenant.status === "churned";

  const trigger = (label: string, d: Exclude<Dialog, null>, variant: "secondary" | "danger" | "primary") => {
    const btn = (
      <Button variant={variant} disabled={!canWrite} onClick={() => openDialog(d)}>
        {label}
      </Button>
    );
    return canWrite ? btn : <ReadOnly>{btn}</ReadOnly>;
  };

  return (
    <>
      <div className="flex flex-wrap gap-2">
        {canReactivate ? trigger("Reactivate tenant", "reactivate", "primary") : null}
        {!churned && canChangePlan ? trigger("Change plan", "plan", "secondary") : null}
        {!churned ? trigger("Set spend cap", "cap", "secondary") : null}
        {canSuspend ? trigger("Suspend tenant", "suspend", "danger") : null}
      </div>

      <ConfirmAction
        open={open === "suspend"}
        onOpenChange={onOpenChange("suspend")}
        title={`Suspend ${tenant.name}?`}
        consequence={
          `Everyone at ${tenant.name} loses access to the app and runs stop starting until you reactivate.` +
          // A live suspend does not cancel open runs: they stop at the next human or approval step.
          (live ? " Runs already in progress keep going until they reach a step this company has to act on." : "")
        }
        confirmLabel="Suspend tenant"
        destructive
        reasonPlaceholder="Chargeback dispute opened by the card issuer"
        onConfirm={async (reason) => {
          await suspend.mutateAsync({ path, body: { reason } });
          toast("Tenant suspended", tenant.name);
          focusPageHeading();
        }}
      />

      <ConfirmAction
        open={open === "reactivate"}
        onOpenChange={onOpenChange("reactivate")}
        title={`Reactivate ${tenant.name}?`}
        consequence={`People at ${tenant.name} get their access back and new runs can start again.`}
        confirmLabel="Reactivate tenant"
        reasonPlaceholder="Payment received, ticket 4821"
        onConfirm={async (reason) => {
          await reactivate.mutateAsync({ path, body: { reason } });
          toast("Tenant reactivated", tenant.name);
          focusPageHeading();
        }}
      />

      <ConfirmAction
        open={open === "plan"}
        onOpenChange={onOpenChange("plan")}
        title={`Change plan for ${tenant.name}?`}
        consequence={`Switches ${tenant.name} from ${tenant.plan} to the plan you pick. Seat and feature limits change straight away.`}
        confirmLabel="Change plan"
        confirmDisabled={plan === tenant.plan}
        reasonPlaceholder="Upgrade requested by the account owner"
        onConfirm={async (reason) => {
          await setPlan.mutateAsync({ path, body: { plan, reason } });
          toast("Plan changed", `${tenant.name} is now on ${plan}.`);
        }}
      >
        <div className="mb-3">
          <label htmlFor="tenant-plan" className="text-sm font-medium">
            New plan
          </label>
          <div className="mt-1">
            <Select<Plan>
              id="tenant-plan"
              label="New plan"
              className="w-full"
              value={plan}
              onValueChange={setPlanValue}
              items={PLANS.map((p) => ({ value: p, label: p }))}
            />
          </div>
          {plan === tenant.plan ? <p className="mt-1 text-xs text-muted">Pick a different plan to continue.</p> : null}
        </div>
      </ConfirmAction>

      <ConfirmAction
        open={open === "cap"}
        onOpenChange={onOpenChange("cap")}
        title={`Set the spend cap for ${tenant.name}?`}
        consequence={`Runs stop starting once ${tenant.name} reaches the monthly cap. It is ${money(tenant.monthlyCap)} now.`}
        confirmLabel="Set spend cap"
        confirmDisabled={capMinor === null || capUnchanged}
        reasonPlaceholder="Raised after a usage review with the owner"
        onConfirm={async (reason) => {
          if (capMinor === null) return;
          await setCap.mutateAsync({ path, body: { monthlyCapMinor: capMinor, reason } });
          toast("Spend cap updated", `${tenant.name} cap is now ${money(capMinor)}.`);
        }}
      >
        <div className="mb-3">
          <label htmlFor="tenant-cap" className="text-sm font-medium">
            Monthly cap (USD)
          </label>
          <input
            id="tenant-cap"
            inputMode="decimal"
            value={capDollars}
            onChange={(e) => setCapDollars(e.target.value)}
            aria-invalid={capMinor === null ? true : undefined}
            aria-describedby="tenant-cap-hint"
            className="tnum mt-1 h-9 w-full rounded-md border border-rule bg-paper px-3 text-sm hover:border-grey-300 focus:border-grey-500 aria-[invalid=true]:border-blocked"
          />
          <p id="tenant-cap-hint" className="mt-1 text-xs text-muted">
            {capMinor === null
              ? DOLLARS_HINT
              : capUnchanged
                ? "Enter a different amount to continue."
                : `Will be saved as ${money(capMinor)}.`}
          </p>
        </div>
      </ConfirmAction>
    </>
  );
}
