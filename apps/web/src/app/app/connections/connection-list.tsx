"use client";

import { useTranslations } from "next-intl";
import { useRef } from "react";
import { Confirm, Modal, ModalClose, focusAfterClose, sameOrLast, useToast } from "@/components/base";
import { Button, ButtonLink, EmptyState, Id, Pill, Section, SimTag } from "@/components/ui";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useErrorText } from "@/lib/api/use-error-text";
import { useIsDemo } from "@/lib/queries/me";
import { useConnections } from "@/lib/queries/org";
import { useConnectApp, useDisconnect, useRevokeGrant } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";
import type { Connection } from "@/lib/types";

const STATUS_TONE = { connected: "ink", not_connected: "quiet", sandbox: "quiet", needs_reauth: "human" } as const;

const LINK_APPS = ["Slack", "QuickBooks Online", "Shopify (live store)", "HubSpot"];

/** Live sign-in links are not available yet, so this explains them instead of faking one. */
export function ConnectDialog({ app, trigger }: { app?: string; trigger: React.ReactElement }) {
  const t = useTranslations("connections.connect");
  const tc = useTranslations("common");
  const demo = useIsDemo();
  return (
    <Modal trigger={trigger} title={app ? t("titleApp", { app }) : t("title")} description={t("description")}>
      {app ? null : (
        <ul className="mt-4 divide-y divide-rule rounded-[10px] border border-rule text-sm">
          {LINK_APPS.map((a) => (
            <li key={a} className="flex items-center justify-between px-3.5 py-2.5">
              {a}
              <span className="text-xs text-muted">{t("liveOnly")}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 rounded-md border border-dashed border-sim/40 bg-sim-soft px-3 py-2 text-[13px] text-sim">
        {demo ? t("demoNote") : t("liveNote")}
      </p>
      <div className="mt-5 flex justify-end">
        <ModalClose render={<Button variant="secondary" />}>{tc("close")}</ModalClose>
      </div>
    </Modal>
  );
}

type Grant = Connection["grants"][number];

/** The app's simulation label: none until it is connected, then Simulated when it serves sandbox data. */
const isSimulated = (c: Connection) => c.status !== "not_connected" && (c.provider === "Mock" || c.mode === "sandbox");

export function ConnectionList() {
  const connections = useConnections();
  return (
    <QueryState query={connections} skeleton={<Skeleton className="h-96" />}>
      {(conns) => (conns.length ? <ConnectionCards conns={conns} /> : <NoConnections />)}
    </QueryState>
  );
}

/** No hired pack needs an app yet. */
function NoConnections() {
  const t = useTranslations("connections");
  return (
    <div className="panel">
      <EmptyState
        action={
          <ButtonLink href="/app/marketplace" variant="secondary" className="h-8">
            {t("browseMarketplace")}
          </ButtonLink>
        }
      >
        {t("empty")}
      </EmptyState>
    </div>
  );
}

/**
 * Connect an app the live workspace lists (it has a connector `key`). In sandbox connector mode it connects
 * to sandbox data; otherwise the API explains that live connections are not available yet.
 */
function ConnectButton({ conn: c, onConnected }: { conn: Connection; onConnected: () => void }) {
  const t = useTranslations("connections");
  const errorText = useErrorText();
  const connect = useConnectApp();
  const toast = useToast();
  const sandbox = c.mode === "sandbox";
  return (
    <Button
      variant="secondary"
      className="h-8"
      data-connect={c.app}
      disabled={connect.isPending}
      onClick={() =>
        connect.mutate(
          { path: { app_name: c.key ?? c.app } },
          {
            onSuccess: () => {
              toast(t("connectedToast", { app: c.app }), sandbox ? t("connectedSandboxBody") : undefined, "sim");
              onConnected();
            },
            onError: (e) => toast(t("connectFailed", { app: c.app }), errorText(e), "blocked"),
          },
        )
      }
    >
      {sandbox ? t("connectSandbox", { app: c.app }) : t("connectApp", { app: c.app })}
    </Button>
  );
}

function ConnectionCards({ conns }: { conns: Connection[] }) {
  const t = useTranslations("connections");
  const tc = useTranslations("common");
  const { ago } = useFormat();
  const errorText = useErrorText();
  const disconnectConnection = useDisconnect();
  const revokeGrant = useRevokeGrant();
  const toast = useToast();
  const demo = useIsDemo();
  const root = useRef<HTMLDivElement>(null);
  // The control that opened the dialog is gone after these actions, so focus moves to the
  // nearest control that still makes sense for the same app.
  const controls = (attr: "connect" | "disconnect" | "revoke", app: string) =>
    [...(root.current?.querySelectorAll<HTMLElement>(`[data-${attr}]`) ?? [])].filter((el) => el.dataset[attr] === app);

  const disconnect = (app: string) => {
    disconnectConnection.mutate(
      { path: { app_name: app } },
      {
        onSuccess: () =>
          demo
            ? toast(t("disconnectedToast", { app }), t("disconnectedToastBody"), "sim")
            : toast(t("disconnectedToast", { app }), t("disconnectedToastBodyLive")),
        onError: (e) => toast(t("disconnectFailed", { app }), errorText(e), "blocked"),
      },
    );
    focusAfterClose(() => controls("connect", app)[0]);
  };
  // The Connect button goes away once the app connects; its card's Disconnect control takes the focus.
  // The card re-renders with the cached row a frame or two later, so look for it a few times.
  const focusDisconnect = (app: string, tries = 5) =>
    requestAnimationFrame(() => {
      const el = controls("disconnect", app)[0];
      if (el) el.focus();
      else if (tries > 1) focusDisconnect(app, tries - 1);
    });
  const revoke = (app: string, grant: Grant, index: number) => {
    revokeGrant.mutate(
      { query: { app, install: grant.install, capability: grant.capability } },
      {
        onSuccess: () => toast(t("revokedToast"), t("revokedToastBody", { install: grant.install, app })),
        onError: (e) => toast(t("revokeFailed"), errorText(e), "blocked"),
      },
    );
    focusAfterClose(() => sameOrLast(controls("revoke", app), index) ?? controls("disconnect", app)[0]);
  };

  return (
    <div ref={root} className="space-y-4">
      {conns.some((c) => c.mode === "sandbox") ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted">
          {/* The tag marks simulated apps, so it shows only once one is connected to sandbox data. */}
          {conns.some(isSimulated) ? <SimTag /> : null}
          {t("sandboxNote")}
        </p>
      ) : null}
      <div className="grid grid-cols-1 items-start gap-4 2xl:grid-cols-2">
        {conns.map((c) => (
          <Section
            key={c.app}
            title={
              <span className="flex items-center gap-2.5">
                {c.app}
                {isSimulated(c) ? <SimTag /> : null}
              </span>
            }
            aside={<Pill tone={STATUS_TONE[c.status]}>{t(`status.${c.status}`)}</Pill>}
          >
            {c.status === "not_connected" ? (
              <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-muted">{t("notConnectedNote", { app: c.app })}</p>
                {c.key ? (
                  <ConnectButton conn={c} onConnected={() => focusDisconnect(c.app)} />
                ) : (
                  <ConnectDialog
                    app={c.app}
                    trigger={
                      <Button variant="secondary" className="h-8" data-connect={c.app}>
                        {t("connectApp", { app: c.app })}
                      </Button>
                    }
                  />
                )}
              </div>
            ) : (
              <div className="grid gap-px bg-rule md:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
                <div className="bg-paper px-5 py-4 text-sm">
                  <div className="label">{t("account")}</div>
                  <div className="mt-0.5">{c.account || "—"}</div>
                  {c.oauthScopes.length ? (
                    <>
                      <div className="label mt-3">{t("scopes")}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {c.oauthScopes.map((s) => (
                          <Id key={s} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
                            {s}
                          </Id>
                        ))}
                      </div>
                    </>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                    {c.lastUsed ? <span>{t("used", { when: ago(c.lastUsed) })}</span> : null}
                    {c.health ? (
                      <span className={c.health.includes("unconfirmed") ? "text-human" : undefined}>{c.health}</span>
                    ) : null}
                    <span>{c.provider === "Mock" ? t("viaMock") : t("viaComposio")}</span>
                  </div>
                  <Confirm
                    danger
                    trigger={
                      <button type="button" data-disconnect={c.app} className="link mt-3 text-xs text-blocked">
                        {t("disconnectApp", { app: c.app })}
                      </button>
                    }
                    title={t("disconnectTitle", { app: c.app })}
                    description={t("disconnectDescription", { app: c.app })}
                    confirmLabel={t("disconnectApp", { app: c.app })}
                    onConfirm={() => disconnect(c.app)}
                  />
                </div>
                <div className="bg-paper">
                  <div className="label px-5 pt-4">{t("grantsHeading")}</div>
                  {c.grants.length ? (
                    <ul className="divide-y divide-rule px-5 pb-2">
                      {c.grants.map((g) => (
                        <li
                          key={`${g.install}-${g.capability}`}
                          className="flex flex-col gap-1 py-2.5 text-sm sm:flex-row sm:items-center sm:justify-between"
                        >
                          <div className="min-w-0">
                            <div>{g.install}</div>
                            <Id className="text-[11px]">{g.capability}</Id>
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            {g.access === "read" ? (
                              <span className="text-grey-700">{tc("readOnly")}</span>
                            ) : g.access === "denied" ? (
                              <Pill tone="blocked">{t("denied")}</Pill>
                            ) : (
                              <span className="text-human">{t("writesWithApproval")}</span>
                            )}
                            {g.access !== "denied" ? (
                              <Confirm
                                trigger={
                                  <button type="button" data-revoke={c.app} className="link text-xs text-muted">
                                    {t("revoke")}
                                  </button>
                                }
                                title={t("revokeTitle")}
                                description={t("revokeDescription", {
                                  install: g.install,
                                  capability: g.capability,
                                  app: c.app,
                                })}
                                confirmLabel={t("revokeConfirm")}
                                onConfirm={() =>
                                  revoke(c.app, g, c.grants.filter((x) => x.access !== "denied").indexOf(g))
                                }
                              />
                            ) : null}
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="px-5 py-3 text-sm text-muted">{t("noPack")}</p>
                  )}
                </div>
              </div>
            )}
          </Section>
        ))}
      </div>
    </div>
  );
}
