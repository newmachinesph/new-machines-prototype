"use client";

import { useState } from "react";
import { Choices, Segmented, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { SimTag } from "@/components/ui";
import { useAddConnector, useAvailableToolkits } from "@/lib/queries/connectors";
import { AUTH_LABEL } from "./connector-state";

type NewStatus = "enabled" | "beta";

/** Picks from the simulated toolkit catalogue. The reason comes from the shared confirm dialog. */
export function AddConnector({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const toast = useToast();
  const toolkits = useAvailableToolkits(open);
  const add = useAddConnector();
  const [slug, setSlug] = useState<string | null>(null);
  const [status, setStatus] = useState<NewStatus>("enabled");
  const chosen = toolkits.data?.find((t) => t.slug === slug);

  return (
    <ConfirmAction
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setSlug(null);
          setStatus("enabled");
        }
      }}
      title="Add a connector"
      consequence="Tenants can connect it from their settings. Defaults start as read permitted, write needing approval, delete and money denied."
      confirmLabel="Add connector"
      confirmDisabled={!chosen}
      reasonPlaceholder="Requested by three pilot tenants"
      onConfirm={async (reason) => {
        if (!chosen) return;
        await add.mutateAsync({ body: { toolkitSlug: chosen.slug, status, reason } });
        toast(`${chosen.name} added as ${status}`);
      }}
    >
      <div className="space-y-4">
        <div>
          <div className="mb-1.5 flex items-center gap-2 text-sm font-medium">
            Available toolkits <SimTag>simulated discovery</SimTag>
          </div>
          {toolkits.isPending ? (
            <p className="text-sm text-muted">Looking for toolkits.</p>
          ) : toolkits.isError ? (
            <p role="alert" className="text-sm text-blocked">
              Could not load the toolkit list. Close this dialog and try again.
            </p>
          ) : toolkits.data.length === 0 ? (
            <p className="text-sm text-muted">Every available toolkit has already been added.</p>
          ) : (
            <div className="max-h-64 overflow-y-auto pr-1">
              <Choices
                label="Toolkit"
                value={slug}
                onValueChange={setSlug}
                options={toolkits.data.map((t) => ({
                  value: t.slug,
                  label: t.name,
                  description: `${t.category}, ${AUTH_LABEL[t.authType]}`,
                }))}
              />
            </div>
          )}
        </div>
        <div>
          <div className="mb-1.5 text-sm font-medium">Start as</div>
          <div className="w-fit">
            <Segmented<NewStatus>
              label="Initial status"
              value={status}
              onValueChange={setStatus}
              options={[
                { value: "enabled", label: "Enabled" },
                { value: "beta", label: "Beta" },
              ]}
            />
          </div>
        </div>
      </div>
    </ConfirmAction>
  );
}
