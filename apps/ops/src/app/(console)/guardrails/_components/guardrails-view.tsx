"use client";

import { useState, type ReactNode } from "react";
import { useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, Id, Pill, Section, SimTag } from "@/components/ui";
import type { Guardrail } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { ago } from "@/lib/format";
import { useGuardrails, useSetGuardrail } from "@/lib/queries/guardrails";
import { useCanWrite } from "@/lib/queries/ops";
import { fieldHint, fieldUnitLabel, formatLimit, fromFieldValue, isMoneyUnit, toFieldValue } from "./limits";

/** The only guardrail the API enforces today; every other switch and limit is stored for the demo. */
const ENFORCED_KEY = "pause_all_runs";
const NOT_ENFORCED = "Stored only in the demo; not enforced yet.";
const PAUSE_COPY = "New runs are refused for every tenant until you turn this off. Runs already in progress continue.";
const isEnforced = (g: Guardrail) => g.key === ENFORCED_KEY;

function Row({ g, children }: { g: Guardrail; children: ReactNode }) {
  return (
    <li className="flex flex-col gap-3 px-5 py-4 md:flex-row md:items-center md:justify-between md:gap-6">
      <div className="min-w-0">
        <div className="text-sm font-semibold">{g.label}</div>
        <p className="mt-0.5 max-w-[68ch] text-[13px] leading-snug text-grey-700">
          {isEnforced(g) ? PAUSE_COPY : `Once enforced: ${g.description}`}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <Id>{g.key}</Id>
          {isEnforced(g) ? null : <SimTag>not enforced</SimTag>}
          <span className="text-xs text-muted">
            Last changed {ago(g.updatedAt)} by <span className="break-all">{g.updatedBy}</span>
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">{children}</div>
    </li>
  );
}

function KillSwitchRow({ g, canWrite }: { g: Guardrail; canWrite: boolean }) {
  const set = useSetGuardrail();
  const toast = useToast();
  const turningOn = !g.enabled;
  const verb = turningOn ? "Turn on" : "Turn off";
  const trigger = (
    <Button variant={turningOn ? "danger" : "secondary"} disabled={!canWrite} aria-label={`${verb} ${g.label}`}>
      {verb}
    </Button>
  );
  return (
    <Row g={g}>
      {g.enabled ? <Pill tone="blocked">{isEnforced(g) ? "On, blocking" : "On"}</Pill> : <Pill tone="quiet">Off</Pill>}
      {canWrite ? (
        <ConfirmAction
          trigger={trigger}
          title={`${verb} "${g.label}"?`}
          consequence={
            isEnforced(g)
              ? turningOn
                ? PAUSE_COPY
                : "New runs can start again for every tenant. Runs already in progress were not affected."
              : `${NOT_ENFORCED} The setting is recorded in the audit log.`
          }
          confirmLabel={`${verb} ${g.label}`}
          destructive={turningOn}
          reasonPlaceholder={
            turningOn ? "Runaway spend on one tenant, see the incident" : "Incident resolved, safe to resume"
          }
          onConfirm={async (reason) => {
            await set.mutateAsync({ path: { key: g.key }, body: { enabled: turningOn, reason } });
            toast(`${g.label} is ${turningOn ? "on" : "off"}`);
          }}
        />
      ) : (
        <ReadOnly>{trigger}</ReadOnly>
      )}
    </Row>
  );
}

function FlagRow({ g, canWrite }: { g: Guardrail; canWrite: boolean }) {
  const set = useSetGuardrail();
  const toast = useToast();
  const next = !g.enabled;
  const verb = next ? "Turn on" : "Turn off";
  const trigger = (
    <button
      type="button"
      role="switch"
      aria-checked={g.enabled}
      aria-label={g.label}
      disabled={!canWrite}
      className={cn(
        "relative h-6 w-10 shrink-0 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        g.enabled ? "border-ink bg-ink" : "border-grey-300 bg-grey-100",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute top-0.5 size-4 rounded-full transition-all",
          g.enabled ? "left-[1.125rem] bg-paper" : "left-0.5 bg-grey-500",
        )}
      />
    </button>
  );
  return (
    <Row g={g}>
      <span className="w-6 text-sm font-medium">{g.enabled ? "On" : "Off"}</span>
      {canWrite ? (
        <ConfirmAction
          trigger={trigger}
          title={`${verb} "${g.label}"?`}
          consequence={`${NOT_ENFORCED} The setting is recorded in the audit log.`}
          confirmLabel={`${verb} flag`}
          reasonPlaceholder="Rolling out after the staging check"
          onConfirm={async (reason) => {
            await set.mutateAsync({ path: { key: g.key }, body: { enabled: next, reason } });
            toast(`${g.label} is ${next ? "on" : "off"}`);
          }}
        />
      ) : (
        <ReadOnly>{trigger}</ReadOnly>
      )}
    </Row>
  );
}

function LimitEdit({ g }: { g: Guardrail }) {
  const set = useSetGuardrail();
  const toast = useToast();
  const [text, setText] = useState(toFieldValue(g));
  const parsed = fromFieldValue(g.unit, text);
  const unchanged = parsed === g.value;
  const inputId = `limit-${g.key}`;
  return (
    <ConfirmAction
      trigger={
        <Button variant="secondary" aria-label={`Edit limit: ${g.label}`}>
          Edit limit
        </Button>
      }
      title={`Edit "${g.label}"`}
      consequence={`${NOT_ENFORCED} The new value is recorded in the audit log.`}
      confirmLabel="Save limit"
      confirmDisabled={parsed === null || unchanged}
      reasonPlaceholder="Raising for the quarter-end rush"
      onOpenChange={(o) => {
        if (o) setText(toFieldValue(g));
      }}
      onConfirm={async (reason) => {
        if (parsed === null) return;
        await set.mutateAsync({ path: { key: g.key }, body: { value: parsed, reason } });
        toast(`${g.label} set to ${formatLimit({ unit: g.unit, value: parsed })}`);
      }}
    >
      <div className="text-sm">
        <label htmlFor={inputId} className="font-medium">
          {g.label} ({fieldUnitLabel(g.unit)})
        </label>
        <input
          id={inputId}
          type="text"
          inputMode={isMoneyUnit(g.unit) ? "decimal" : "numeric"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-invalid={parsed === null ? true : undefined}
          aria-describedby={`${inputId}-hint`}
          className="tnum mt-1.5 block h-9 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none focus:border-ink aria-[invalid]:border-blocked"
        />
        <p id={`${inputId}-hint`} className="mt-1 text-xs text-muted">
          {parsed === null
            ? fieldHint(g.unit)
            : unchanged
              ? "Same as the current value."
              : `Current: ${formatLimit(g)}`}
        </p>
      </div>
    </ConfirmAction>
  );
}

function LimitRow({ g, canWrite }: { g: Guardrail; canWrite: boolean }) {
  return (
    <Row g={g}>
      <span className="tnum text-sm font-semibold">{formatLimit(g)}</span>
      {canWrite ? (
        <LimitEdit g={g} />
      ) : (
        <ReadOnly>
          <Button variant="secondary" disabled>
            Edit limit
          </Button>
        </ReadOnly>
      )}
    </Row>
  );
}

export function GuardrailsView() {
  const q = useGuardrails();
  const canWrite = useCanWrite();
  return (
    <QueryState query={q} skeleton={<Skeleton className="h-96" />}>
      {(all) => {
        const kill = all.filter((g) => g.kind === "kill_switch");
        const flags = all.filter((g) => g.kind === "flag");
        const limits = all.filter((g) => g.kind === "limit");
        // Only pause_all_runs is enforced by the API; the others are stored settings, so they never count as blocking.
        const blocking = kill.some((g) => g.enabled && isEnforced(g));
        const on = kill.filter((g) => g.enabled).length;
        return (
          <div className="space-y-6">
            <Section
              title="Kill switches"
              aside={
                blocking ? (
                  <Pill tone="blocked">Blocking new runs</Pill>
                ) : on > 0 ? (
                  <Pill tone="quiet">{on} on, not enforced</Pill>
                ) : (
                  <Pill tone="quiet">None active</Pill>
                )
              }
              className={blocking ? "border-blocked/40" : undefined}
            >
              <ul className="divide-y divide-rule">
                {kill.map((g) => (
                  <KillSwitchRow key={g.key} g={g} canWrite={canWrite} />
                ))}
              </ul>
            </Section>
            <Section title="Feature flags" aside={<SimTag>not enforced</SimTag>}>
              <p className="border-b border-rule px-5 py-2.5 text-xs text-muted">{NOT_ENFORCED}</p>
              <ul className="divide-y divide-rule">
                {flags.map((g) => (
                  <FlagRow key={g.key} g={g} canWrite={canWrite} />
                ))}
              </ul>
            </Section>
            <Section title="Limits" aside={<SimTag>not enforced</SimTag>}>
              <p className="border-b border-rule px-5 py-2.5 text-xs text-muted">{NOT_ENFORCED}</p>
              <ul className="divide-y divide-rule">
                {limits.map((g) => (
                  <LimitRow key={g.key} g={g} canWrite={canWrite} />
                ))}
              </ul>
            </Section>
          </div>
        );
      }}
    </QueryState>
  );
}
