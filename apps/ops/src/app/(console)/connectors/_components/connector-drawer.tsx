"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Activity, X } from "lucide-react";
import { useRef, useState } from "react";
import { BACKDROP, focusAfterClose, Segmented, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { Button, Id, KeyValues, Pill, SimTag, type Tone } from "@/components/ui";
import { errorText } from "@/lib/api/error-text";
import type { ConnectorDefaults, ConnectorEntry } from "@/lib/api/gen/types.gen";
import { ago, count, pct } from "@/lib/format";
import {
  useDisableConnector,
  useEnableConnector,
  useHealthCheckConnector,
  useSetConnectorDefaults,
} from "@/lib/queries/connectors";
import { useCanWrite, useOpsWorkspace } from "@/lib/queries/ops";
import { cn } from "@/lib/cn";
import {
  ACTION_CLASSES,
  AUTH_LABEL,
  type Decision,
  DECISION_LABEL,
  describeChanges,
  diffDefaults,
  isHighErrorRate,
  STATUS_LABEL,
} from "./connector-state";
import { ReadOnly } from "@/components/read-only";

export const STATUS_TONE: Record<ConnectorEntry["status"], Tone> = {
  enabled: "machine",
  beta: "human",
  disabled: "quiet",
};

const DECISION_OPTIONS = (["permit", "require_approval", "deny"] as const).map((value) => ({
  value,
  label: DECISION_LABEL[value],
}));

const SHEET =
  "fixed inset-y-0 right-0 z-50 flex w-[min(30rem,100vw)] flex-col border-l border-rule bg-paper shadow-[0_8px_28px_rgb(17_17_17/0.12)] outline-none transition-transform duration-200 data-[ending-style]:translate-x-full data-[starting-style]:translate-x-full";

/** A right-side sheet over the table. The connector stays mounted through the close animation. */
export function ConnectorDrawer({
  connector,
  onClose,
}: {
  connector: ConnectorEntry | undefined;
  onClose: () => void;
}) {
  const [shown, setShown] = useState<ConnectorEntry | undefined>(connector);
  if (connector && connector !== shown) setShown(connector);

  return (
    <Dialog.Root open={Boolean(connector)} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Backdrop className={BACKDROP} />
        <Dialog.Popup className={SHEET}>{shown ? <DrawerBody connector={shown} /> : null}</Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function DrawerBody({ connector }: { connector: ConnectorEntry }) {
  const canWrite = useCanWrite();
  const toast = useToast();
  const healthCheck = useHealthCheckConnector();
  const enable = useEnableConnector();
  const disable = useDisableConnector();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const focusTitle = () => focusAfterClose(() => titleRef.current);
  const check = connector.lastHealthCheck;
  const disabled = connector.status === "disabled";
  // Health checks are simulated: the live workspace has no probe, and a connector without a check offers none.
  const live = useOpsWorkspace() === "live";
  const showHealth = !live && check != null;

  async function runHealthCheck() {
    try {
      const next = await healthCheck.mutateAsync({ path: { connector_id: connector.id } });
      const result = next.lastHealthCheck;
      if (!result) toast(`Health check for ${connector.app} did not run`, "No result came back.", "blocked");
      else if (result.ok) toast(`${connector.app} is healthy`, `${result.latencyMs} ms. Simulated result.`, "sim");
      else toast(`${connector.app} failed its health check`, result.note ?? "Simulated result.", "blocked");
    } catch (e) {
      toast(`Health check for ${connector.app} did not run`, errorText(e), "blocked");
    }
  }

  const actionButtons = canWrite ? (
    <>
      {showHealth ? (
        <Button variant="secondary" onClick={runHealthCheck} disabled={healthCheck.isPending}>
          <Activity className="size-4" aria-hidden />
          Run health check
        </Button>
      ) : null}
      {disabled ? (
        <ConfirmAction
          trigger={<Button variant="secondary">Enable connector</Button>}
          title={`Enable ${connector.app}?`}
          consequence={`Tenants can connect ${connector.app} again. Their connections start as not connected until they sign in.`}
          confirmLabel="Enable connector"
          reasonPlaceholder="Provider incident resolved"
          onConfirm={async (reason) => {
            await enable.mutateAsync({ path: { connector_id: connector.id }, body: { reason } });
            toast(`${connector.app} enabled`);
            focusTitle();
          }}
        />
      ) : (
        <ConfirmAction
          trigger={<Button variant="danger">Disable connector</Button>}
          title={`Disable ${connector.app}?`}
          consequence={`Tenants can no longer use ${connector.app}. Their connections are marked not connected and grants are cleared.`}
          confirmLabel="Disable connector"
          destructive
          reasonPlaceholder="Provider reported a security incident"
          onConfirm={async (reason) => {
            await disable.mutateAsync({ path: { connector_id: connector.id }, body: { reason } });
            toast(`${connector.app} disabled`);
            focusTitle();
          }}
        />
      )}
    </>
  ) : (
    <>
      {showHealth ? (
        <ReadOnly>
          <Button variant="secondary" disabled>
            <Activity className="size-4" aria-hidden />
            Run health check
          </Button>
        </ReadOnly>
      ) : null}
      <ReadOnly>
        <Button variant="secondary" disabled>
          {disabled ? "Enable connector" : "Disable connector"}
        </Button>
      </ReadOnly>
    </>
  );

  return (
    <>
      <header className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
        <div className="min-w-0">
          <Dialog.Title ref={titleRef} tabIndex={-1} className="text-lg font-semibold outline-none">
            {connector.app}
          </Dialog.Title>
          <Dialog.Description className="mt-0.5 text-sm text-muted">
            {connector.category}, via {connector.provider}
          </Dialog.Description>
        </div>
        <Dialog.Close
          aria-label="Close"
          className="grid size-8 shrink-0 place-items-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </Dialog.Close>
      </header>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={STATUS_TONE[connector.status]}>{STATUS_LABEL[connector.status]}</Pill>
          <Id>{connector.id}</Id>
        </div>
        <div className="flex flex-wrap gap-2">{actionButtons}</div>

        <section aria-labelledby={showHealth ? "drawer-health" : "drawer-usage"}>
          {showHealth ? (
            <h3 id="drawer-health" className="h-section flex items-center gap-2">
              Health <SimTag>simulated</SimTag>
            </h3>
          ) : (
            <h3 id="drawer-usage" className="h-section">
              Usage
            </h3>
          )}
          <KeyValues
            rows={[
              ...(showHealth && check
                ? [
                    {
                      label: "Last check",
                      value: (
                        <span className="flex flex-wrap items-center gap-2">
                          <Pill tone={check.ok ? "ink" : "blocked"}>{check.ok ? "Passed" : "Failed"}</Pill>
                          <span className="tnum">{check.latencyMs} ms</span>
                          <span className="text-muted">{ago(check.at)}</span>
                        </span>
                      ),
                    },
                    ...(check.note ? [{ label: "Note", value: check.note }] : []),
                  ]
                : []),
              {
                label: "Error rate",
                value: (
                  <span className={cn("tnum", isHighErrorRate(connector.errorRate) && "font-medium text-blocked")}>
                    {pct(connector.errorRate)}
                    {isHighErrorRate(connector.errorRate) ? " (above the 5% limit)" : ""}
                  </span>
                ),
              },
              { label: "Calls today", value: <span className="tnum">{count(connector.callsToday)}</span> },
              { label: "Tenants connected", value: <span className="tnum">{count(connector.tenantsConnected)}</span> },
              { label: "Sign-in", value: AUTH_LABEL[connector.authType] },
            ]}
          />
        </section>

        <DefaultsEditor
          key={`${connector.id}:${JSON.stringify(connector.defaults)}`}
          connector={connector}
          canWrite={canWrite}
        />

        <section aria-labelledby="drawer-scopes">
          <h3 id="drawer-scopes" className="h-section">
            Scopes requested
          </h3>
          {connector.scopes.length ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {connector.scopes.map((s) => (
                <li key={s}>
                  <Id className="rounded bg-grey-100 px-1.5 py-0.5">{s}</Id>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted">No scopes. This connector uses an API key.</p>
          )}
        </section>
      </div>
    </>
  );
}

function DefaultsEditor({ connector, canWrite }: { connector: ConnectorEntry; canWrite: boolean }) {
  const toast = useToast();
  const save = useSetConnectorDefaults();
  const [draft, setDraft] = useState<ConnectorDefaults>(connector.defaults);
  const changes = diffDefaults(connector.defaults, draft);

  return (
    <section aria-labelledby="drawer-defaults">
      <h3 id="drawer-defaults" className="h-section">
        Default decisions
      </h3>
      <p className="mt-1 text-sm text-muted">
        What happens when a pack uses {connector.app}, unless a tenant policy says otherwise.
      </p>
      <div className="mt-3 space-y-4">
        {ACTION_CLASSES.map((a) => (
          <div key={a.key}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium">{a.label}</span>
              <span className="text-xs text-muted">{a.hint}</span>
            </div>
            <div className="w-fit max-w-full overflow-x-auto">
              {canWrite ? (
                <Segmented<Decision>
                  label={`${a.label} decision`}
                  value={draft[a.key]}
                  onValueChange={(v) => setDraft((d) => ({ ...d, [a.key]: v }))}
                  options={DECISION_OPTIONS}
                />
              ) : (
                <span className="inline-flex h-9 items-center rounded-md border border-rule bg-grey-50 px-3 text-sm font-medium">
                  <span className="sr-only">{a.label} decision: </span>
                  {DECISION_LABEL[draft[a.key]]}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4">
        {!canWrite ? (
          <ReadOnly>
            <Button disabled>Save defaults</Button>
          </ReadOnly>
        ) : (
          <ConfirmAction
            trigger={<Button disabled={changes.length === 0}>Save defaults</Button>}
            title={`Change ${connector.app} defaults?`}
            consequence={`${describeChanges(changes)} This applies to every tenant that has not set its own policy.`}
            confirmLabel="Save defaults"
            reasonPlaceholder="Finance asked for approval on every refund"
            onConfirm={async (reason) => {
              await save.mutateAsync({ path: { connector_id: connector.id }, body: { defaults: draft, reason } });
              toast(`${connector.app} defaults saved`);
            }}
          />
        )}
        {changes.length === 0 && canWrite ? (
          <p className="mt-1.5 text-xs text-muted">Change a decision to save.</p>
        ) : null}
      </div>
    </section>
  );
}
