"use client";

import { useTranslations } from "next-intl";
import { type ChangeEvent, type FormEvent, useId, useState } from "react";
import { Modal } from "@/components/base";
import { Button, Callout } from "@/components/ui";
import type { McpServer } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useAddMcpServer, useMcpServers } from "@/lib/queries/mcp";
import { useOrgId } from "@/lib/queries/me";
import { McpToolGroups } from "./mcp-tools";

export const INPUT_CLASS =
  "mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm font-normal outline-none focus:border-ink";
const EMPTY = { name: "", url: "", headerName: "Authorization", token: "" };
type Field = keyof typeof EMPTY;

/** "Add your own MCP server": name, address, header and token. Once the server answers, the dialog shows
 * its tools in their groups with their switches, then Done. */
export function AddMcpServer() {
  const t = useTranslations("connections.mcp");
  const orgId = useOrgId() ?? "";
  const add = useAddMcpServer();
  const servers = useMcpServers();
  const errorText = useErrorText();
  const ids = useId();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [added, setAdded] = useState<McpServer | null>(null);
  const [error, setError] = useState<string | null>(null);
  // After a switch, the list is fresher than the answer to the add.
  const shown = added ? (servers.data?.find((s) => s.id === added.id) ?? added) : null;

  const change = (next: boolean) => {
    setOpen(next);
    if (!next) {
      add.reset();
      setForm(EMPTY);
      setAdded(null);
      setError(null);
    }
  };
  const field = (name: Field) => ({
    value: form[name],
    "aria-describedby": `${ids}-${name}`,
    onChange: (e: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [name]: e.target.value }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    add.mutate(
      {
        path: { org_id: orgId },
        body: {
          name: form.name.trim(),
          url: form.url.trim(),
          headerName: form.headerName.trim() || "Authorization",
          token: form.token,
        },
      },
      {
        onSuccess: (server) => {
          add.reset();
          setAdded(server);
          setForm(EMPTY);
        },
        onError: (err) => setError(errorText(err)),
      },
    );
  };
  const hint = (name: Field, text: string) => (
    <p id={`${ids}-${name}`} className="mt-1 text-xs text-muted">
      {text}
    </p>
  );

  return (
    <Modal
      open={open}
      onOpenChange={change}
      trigger={<Button variant="secondary">{t("add")}</Button>}
      title={shown ? t("toolsTitle", { name: shown.name }) : t("dialogTitle")}
      description={shown ? t("toolsLede") : t("dialogDescription")}
    >
      {shown ? (
        <>
          <McpToolGroups server={shown} />
          <div className="mt-5 flex justify-end">
            <Button onClick={() => change(false)}>{t("done")}</Button>
          </div>
        </>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-medium">
              {t("name")}
              <input required maxLength={60} className={INPUT_CLASS} {...field("name")} />
            </label>
            {hint("name", t("nameHint"))}
          </div>
          <div>
            <label className="block text-sm font-medium">
              {t("url")}
              <input required type="url" inputMode="url" maxLength={2048} className={INPUT_CLASS} {...field("url")} />
            </label>
            {hint("url", t("urlHint"))}
          </div>
          <div>
            <label className="block text-sm font-medium">
              {t("header")}
              <input required maxLength={64} className={INPUT_CLASS} {...field("headerName")} />
            </label>
            {hint("headerName", t("headerHint"))}
          </div>
          <div>
            <label className="block text-sm font-medium">
              {t("token")}
              <input
                required
                type="password"
                autoComplete="off"
                maxLength={4096}
                className={INPUT_CLASS}
                {...field("token")}
              />
            </label>
            {hint("token", t("tokenHint"))}
          </div>
          {error ? (
            <Callout tone="blocked" title={t("addFailed")}>
              {error}
            </Callout>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" disabled={add.isPending}>
              {add.isPending ? t("connecting") : t("connect")}
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
