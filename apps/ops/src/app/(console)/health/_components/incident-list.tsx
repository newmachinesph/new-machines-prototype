"use client";

import { useRef, useState } from "react";
import { focusAfterClose, Select, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button, Id, Pill, Section, type Tone } from "@/components/ui";
import type { Incident } from "@/lib/api/gen/types.gen";
import { ago, dateTime } from "@/lib/format";
import { useUpdateIncident } from "@/lib/queries/health";
import { nextStatuses, SEVERITY_LABEL, STATUS_LABEL, type IncidentStatus, type Severity } from "./incidents";

const SEVERITY_TONE: Record<Severity, Tone> = { sev1: "blocked", sev2: "human", sev3: "quiet" };
const STATUS_TONE: Record<IncidentStatus, Tone> = { investigating: "blocked", monitoring: "human", resolved: "ink" };

function PostUpdate({ incident, onDone }: { incident: Incident; onDone: () => void }) {
  const update = useUpdateIncident();
  const toast = useToast();
  const options = nextStatuses(incident.status);
  const [status, setStatus] = useState<IncidentStatus>(incident.status);
  const [text, setText] = useState("");
  const resolving = status === "resolved";
  const textId = `update-${incident.id}`;
  return (
    <ConfirmAction
      trigger={<Button variant="secondary">Post update</Button>}
      title={`Post an update to "${incident.title}"`}
      consequence={
        resolving
          ? "Resolving closes the incident. A resolved incident cannot be reopened or updated."
          : "The update is added to the incident timeline and recorded in the audit log."
      }
      confirmLabel={resolving ? "Resolve incident" : "Post update"}
      confirmDisabled={text.trim() === ""}
      reasonPlaceholder="Vendor confirmed the fix is rolled out"
      onOpenChange={(o) => {
        if (o) {
          setStatus(incident.status);
          setText("");
        }
      }}
      onConfirm={async (reason) => {
        await update.mutateAsync({
          path: { incident_id: incident.id },
          body: { status, text: text.trim(), reason },
        });
        toast(resolving ? "Incident resolved" : "Update posted", incident.title);
        onDone();
      }}
    >
      <div className="space-y-4 text-sm">
        <div>
          <label htmlFor={`status-${incident.id}`} className="font-medium">
            Status
          </label>
          <div className="mt-1.5">
            <Select
              id={`status-${incident.id}`}
              label="Status"
              value={status}
              onValueChange={setStatus}
              items={options.map((v) => ({ value: v, label: STATUS_LABEL[v] }))}
              className="w-full"
            />
          </div>
        </div>
        <div>
          <label htmlFor={textId} className="font-medium">
            Update
          </label>
          <textarea
            id={textId}
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={1000}
            placeholder="What changed, and what happens next"
            className="mt-1.5 block w-full resize-y rounded-md border border-grey-300 bg-paper px-3 py-2 text-sm outline-none focus:border-ink"
          />
        </div>
      </div>
    </ConfirmAction>
  );
}

function IncidentCard({
  incident,
  names,
  canWrite,
  live,
  onDone,
}: {
  incident: Incident;
  names: Map<string, string>;
  canWrite: boolean;
  live: boolean;
  onDone: () => void;
}) {
  const open = incident.status !== "resolved";
  return (
    <li className="px-5 py-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={SEVERITY_TONE[incident.severity]}>{SEVERITY_LABEL[incident.severity]}</Pill>
            <Pill tone={STATUS_TONE[incident.status]} live={open}>
              {STATUS_LABEL[incident.status]}
            </Pill>
            <Id>{incident.id}</Id>
          </div>
          <h3 className="mt-2 text-sm font-semibold">{incident.title}</h3>
          <p className="mt-0.5 text-xs text-muted">
            Started {dateTime(incident.startedAt)} UTC
            {incident.resolvedAt ? `, resolved ${dateTime(incident.resolvedAt)} UTC` : ""}. Affects{" "}
            {incident.services.length
              ? incident.services.map((k) => names.get(k) ?? k).join(", ")
              : "no listed services"}
            .
          </p>
        </div>
        {open && !live ? (
          canWrite ? (
            <PostUpdate incident={incident} onDone={onDone} />
          ) : (
            <ReadOnly>
              <Button variant="secondary" disabled>
                Post update
              </Button>
            </ReadOnly>
          )
        ) : null}
      </div>
      <ol className="mt-3 space-y-2 border-l border-rule pl-4" aria-label={`Updates for ${incident.title}`}>
        {[...incident.updates].reverse().map((u) => (
          <li key={`${u.at}|${u.by}|${u.text}`} className="text-sm">
            <div className="text-xs text-muted">
              <span className="tnum">{dateTime(u.at)} UTC</span>, {ago(u.at)}, <span className="break-all">{u.by}</span>
            </div>
            <p className="mt-0.5 leading-snug">{u.text}</p>
          </li>
        ))}
      </ol>
    </li>
  );
}

export function IncidentList({
  incidents,
  names,
  canWrite,
  live = false,
  aside,
}: {
  incidents: Incident[];
  names: Map<string, string>;
  canWrite: boolean;
  /** The live workspace's incidents are samples: no updates can be posted. */
  live?: boolean;
  aside: React.ReactNode;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeading = () => focusAfterClose(() => headingRef.current);
  return (
    <Section title="Incidents" aside={aside} headingRef={headingRef}>
      {incidents.length === 0 ? (
        <p className="px-5 py-8 text-sm text-muted">
          {live ? "No incidents." : "No incidents. Declare one if something is wrong."}
        </p>
      ) : (
        <ul className="divide-y divide-rule">
          {incidents.map((i) => (
            <IncidentCard key={i.id} incident={i} names={names} canWrite={canWrite} live={live} onDone={focusHeading} />
          ))}
        </ul>
      )}
    </Section>
  );
}
