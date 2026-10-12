"use client";

import { useState } from "react";
import { Checkbox, Select, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button } from "@/components/ui";
import type { ServiceStatus } from "@/lib/api/gen/types.gen";
import { useDeclareIncident } from "@/lib/queries/health";
import { SEVERITY_LABEL, type Severity } from "./incidents";

const SEVERITY_ITEMS = (Object.keys(SEVERITY_LABEL) as Severity[]).map((v) => ({ value: v, label: SEVERITY_LABEL[v] }));

export function DeclareIncident({
  open,
  onOpenChange,
  services,
  canWrite,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  services: ServiceStatus[];
  canWrite: boolean;
}) {
  const declare = useDeclareIncident();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<Severity>("sev3");
  const [picked, setPicked] = useState<string[]>([]);
  // Reset on the rising edge of `open`: it is controlled, so the dialog's own onOpenChange(true) never fires.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setTitle("");
      setSeverity("sev3");
      setPicked([]);
    }
  }
  const toggle = (key: string, on: boolean) => setPicked((p) => (on ? [...p, key] : p.filter((k) => k !== key)));

  return (
    <>
      {canWrite ? (
        <Button onClick={() => onOpenChange(true)}>Declare incident</Button>
      ) : (
        <ReadOnly>
          <Button disabled>Declare incident</Button>
        </ReadOnly>
      )}
      <ConfirmAction
        open={open && canWrite}
        onOpenChange={onOpenChange}
        title="Declare an incident"
        consequence="The incident is listed on this page and recorded in the audit log. Post updates as you learn more."
        confirmLabel="Declare incident"
        confirmDisabled={title.trim() === "" || picked.length === 0}
        reasonPlaceholder="Error rate on the API doubled in the last 10 minutes"
        onConfirm={async (reason) => {
          const created = await declare.mutateAsync({
            body: { title: title.trim(), severity, services: picked, reason },
          });
          toast("Incident declared", created.title);
        }}
      >
        <div className="space-y-4 text-sm">
          <div>
            <label htmlFor="incident-title" className="font-medium">
              Title
            </label>
            <input
              id="incident-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              placeholder="Vertex AI latency elevated"
              className="mt-1.5 block h-9 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none focus:border-ink"
            />
          </div>
          <div>
            <label htmlFor="incident-severity" className="font-medium">
              Severity
            </label>
            <div className="mt-1.5">
              <Select
                id="incident-severity"
                label="Severity"
                value={severity}
                onValueChange={setSeverity}
                items={SEVERITY_ITEMS}
                className="w-full"
              />
            </div>
          </div>
          <fieldset>
            <legend className="font-medium">Affected services</legend>
            <p className="mt-0.5 text-xs text-muted">Pick at least one.</p>
            <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
              {services.map((s) => (
                <Checkbox key={s.key} checked={picked.includes(s.key)} onCheckedChange={(on) => toggle(s.key, on)}>
                  {s.name}
                </Checkbox>
              ))}
            </div>
          </fieldset>
        </div>
      </ConfirmAction>
    </>
  );
}
