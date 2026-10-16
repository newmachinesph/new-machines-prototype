"use client";

import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { Confirm, Modal, ModalClose, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, Callout, Pill, Section } from "@/components/ui";
import type { McpServer } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useMcpServers, useRefreshMcpServer, useRemoveMcpServer, useReplaceMcpToken } from "@/lib/queries/mcp";
import { useIsLive, useMe, useOrgId } from "@/lib/queries/me";
import { AddMcpServer, INPUT_CLASS } from "./add-mcp-server";
import { McpToolGroups } from "./mcp-tools";

const MANAGERS = new Set(["owner", "admin"]);
const STATUS_TONE = { active: "ink", failing: "human", removed: "quiet" } as const;

/** The org's own MCP servers (live workspace only): owners and admins add and manage them; members look. */
export function McpServers() {
  const t = useTranslations("connections.mcp");
  const live = useIsLive();
  const role = useMe().data?.role ?? "";
  const servers = useMcpServers();
  if (!live) return null;
  const canManage = MANAGERS.has(role);
  return (
    <Section className="mt-6" title={t("heading")} aside={canManage ? <AddMcpServer /> : null}>
      <p className="px-5 pt-3 text-sm text-grey-700">{t("lede")}</p>
      {canManage ? null : <p className="px-5 pt-1 text-xs text-muted">{t("askAdmin")}</p>}
      <QueryState query={servers} skeleton={<Skeleton className="m-5 h-24" />}>
        {(list) =>
          list.length ? (
            <ul className="divide-y divide-rule">
              {list.map((server) => (
                <ServerCard key={server.id} server={server} canManage={canManage} />
              ))}
            </ul>
          ) : (
            <p className="px-5 py-6 text-sm text-muted">{t("empty")}</p>
          )
        }
      </QueryState>
    </Section>
  );
}

function ServerCard({ server, canManage }: { server: McpServer; canManage: boolean }) {
  const t = useTranslations("connections.mcp");
  const orgId = useOrgId() ?? "";
  const path = { org_id: orgId, server_id: server.id };
  const refresh = useRefreshMcpServer();
  const remove = useRemoveMcpServer();
  const toast = useToast();
  const errorText = useErrorText();
  const tokenLine = server.tokenLast4 ? ` · ${t("tokenEnds", { last4: server.tokenLast4 })}` : "";
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{server.name}</h3>
        <Pill tone={STATUS_TONE[server.status]}>{t(`status.${server.status}`)}</Pill>
      </div>
      <p className="mt-1 text-xs break-all text-muted">{server.url}</p>
      <p className="mt-1 text-sm">
        {t("toolCount", { count: server.toolCount })}
        {tokenLine}
      </p>
      {server.lastError ? <p className="mt-1 text-xs text-blocked">{t(`lastError.${server.lastError}`)}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <ToolsDialog server={server} canManage={canManage} />
        {canManage ? (
          <>
            <Button
              variant="secondary"
              aria-label={t("refreshFor", { name: server.name })}
              disabled={refresh.isPending}
              onClick={() =>
                refresh.mutate(
                  { path },
                  {
                    onSuccess: (s) =>
                      toast(t("refreshedToast"), t("refreshedToastBody", { name: s.name, count: s.toolCount })),
                    onError: (err) => toast(t("refreshFailed"), errorText(err), "blocked"),
                  },
                )
              }
            >
              {t("refresh")}
            </Button>
            <ReplaceToken server={server} />
            <Confirm
              danger
              trigger={
                <Button variant="danger" aria-label={t("removeFor", { name: server.name })}>
                  {t("remove")}
                </Button>
              }
              title={t("removeTitle", { name: server.name })}
              description={t("removeDescription")}
              confirmLabel={t("removeConfirm")}
              onConfirm={() =>
                remove.mutate(
                  { path },
                  {
                    onSuccess: () => toast(t("removedToast", { name: server.name })),
                    onError: (err) => toast(t("removeFailed"), errorText(err), "blocked"),
                  },
                )
              }
            />
          </>
        ) : null}
      </div>
    </li>
  );
}

function ToolsDialog({ server, canManage }: { server: McpServer; canManage: boolean }) {
  const t = useTranslations("connections.mcp");
  return (
    <Modal
      trigger={
        <Button variant="ghost" aria-label={t("showToolsFor", { name: server.name })}>
          {t("showTools")}
        </Button>
      }
      title={t("showToolsFor", { name: server.name })}
      description={t("toolsLede")}
    >
      <McpToolGroups server={server} canSwitch={canManage} />
      <div className="mt-5 flex justify-end">
        <ModalClose render={<Button />}>{t("done")}</ModalClose>
      </div>
    </Modal>
  );
}

function ReplaceToken({ server }: { server: McpServer }) {
  const t = useTranslations("connections.mcp");
  const orgId = useOrgId() ?? "";
  const replace = useReplaceMcpToken();
  const toast = useToast();
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const change = (next: boolean) => {
    setOpen(next);
    if (!next) {
      replace.reset();
      setToken("");
      setError(null);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    replace.mutate(
      { path: { org_id: orgId, server_id: server.id }, body: { token } },
      {
        onSuccess: () => {
          replace.reset();
          change(false);
          toast(t("replacedToast"));
        },
        onError: (err) => setError(errorText(err)),
      },
    );
  };
  return (
    <Modal
      open={open}
      onOpenChange={change}
      trigger={
        <Button variant="secondary" aria-label={t("replaceTokenFor", { name: server.name })}>
          {t("replaceToken")}
        </Button>
      }
      title={t("replaceTokenTitle", { name: server.name })}
      description={t("replaceTokenDescription")}
    >
      <form onSubmit={submit} className="mt-4 space-y-3">
        <label className="block text-sm font-medium">
          {t("token")}
          <input
            required
            type="password"
            autoComplete="off"
            maxLength={4096}
            className={INPUT_CLASS}
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>
        {error ? (
          <Callout tone="blocked" title={t("replaceFailed")}>
            {error}
          </Callout>
        ) : null}
        <div className="flex justify-end">
          <Button type="submit" disabled={replace.isPending}>
            {t("replaceTokenConfirm")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
