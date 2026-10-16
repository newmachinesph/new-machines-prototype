"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import {
  Checkbox,
  Choices,
  Confirm,
  Modal,
  ModalClose,
  focusAfterClose,
  sameOrLast,
  useToast,
} from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, Id, Pill, Section } from "@/components/ui";
import type { CreateTokenRequest } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useIsDemo, useOrgId } from "@/lib/queries/me";
import { useCreateToken, useInvite, useMembers, useRevokeToken, useTokens } from "@/lib/queries/workspace";
import type { McpToken } from "@/lib/types";
import { useFormat } from "@/lib/use-format";

type Scope = CreateTokenRequest["scopes"][number];

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/** The role names the API sends, which the messages translate; any other name shows as it came. */
const ROLE_NAMES = ["Owner", "Admin", "Member", "Reviewer"] as const;
type RoleName = (typeof ROLE_NAMES)[number];
const isRoleName = (role: string): role is RoleName => (ROLE_NAMES as readonly string[]).includes(role);

export function MembersSection() {
  const t = useTranslations("settings.members");
  const tc = useTranslations("common");
  const errorText = useErrorText();
  const membersQuery = useMembers();
  const members = membersQuery.data ?? [];
  const inviteMember = useInvite();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"Member" | "Admin">("Member");
  const toast = useToast();
  const orgId = useOrgId();
  const demo = useIsDemo();
  const taken = members.some((m) => m.email.toLowerCase() === email.trim().toLowerCase());
  const valid = EMAIL.test(email.trim()) && !taken && orgId !== undefined;

  const invite = () => {
    const address = email.trim();
    if (!orgId) return;
    inviteMember.mutate(
      { path: { org_id: orgId }, body: { email: address, role } },
      {
        onSuccess: () => {
          const values = { address, role: t(`rolesLower.${role}`) };
          if (demo) toast(t("sentToast"), t("sentToastBody", values), "sim");
          else toast(t("sentToast"), t("sentToastBodyLive", values));
          setOpen(false);
          setEmail("");
        },
        onError: (e) => toast(t("sendFailed"), errorText(e), "blocked"),
      },
    );
  };

  return (
    <Section
      title={t("title")}
      aside={
        <Modal
          open={open}
          onOpenChange={setOpen}
          trigger={
            <Button variant="secondary" className="h-10 sm:h-8">
              {t("invite")}
            </Button>
          }
          title={t("inviteTitle")}
          description={t("inviteDescription")}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (valid) invite();
            }}
            className="mt-4 space-y-4"
          >
            <label className="block text-sm">
              <span className="font-medium">{t("email")}</span>
              <input
                name="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("emailPlaceholder")}
                autoComplete="off"
                className="mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
              />
              {taken ? <span className="mt-1 block text-xs text-blocked">{t("taken")}</span> : null}
            </label>
            <fieldset>
              <legend className="mb-1.5 text-sm font-medium">{t("role")}</legend>
              <Choices
                label={t("role")}
                value={role}
                onValueChange={setRole}
                options={[
                  { value: "Member", label: t("roles.Member"), description: t("roleHelp.Member") },
                  { value: "Admin", label: t("roles.Admin"), description: t("roleHelp.Admin") },
                ]}
              />
            </fieldset>
            <div className="flex justify-end gap-2">
              <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
              <Button type="submit" disabled={!valid || inviteMember.isPending}>
                {t("send")}
              </Button>
            </div>
          </form>
        </Modal>
      }
    >
      <QueryState query={membersQuery} skeleton={<Skeleton className="h-40 rounded-none" />}>
        {(list) => (
          <ul className="divide-y divide-rule">
            {list.map((m) => (
              <li key={m.email} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="min-w-0">
                  <div className="truncate font-medium">{m.name}</div>
                  {/* The API's `via` is a status word ("Signed in"), not a sign-in method, so only the email shows. */}
                  <div className="truncate text-xs text-muted">{m.pending ? t("pendingNote") : m.email}</div>
                </div>
                {m.pending ? (
                  <Pill tone="quiet">{t("invited")}</Pill>
                ) : (
                  <span className="text-grey-700">{isRoleName(m.role) ? t(`roles.${m.role}`) : m.role}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Section>
  );
}

const SCOPES: Scope[] = ["agents:read", "runs:read", "runs:start", "approvals:list"];

/** How a token is shown: its prefix, hidden middle and last four characters (older tokens have no last four). */
export const maskedToken = (tok: Pick<McpToken, "prefix" | "last4">) =>
  `${tok.prefix ?? "nm_pat_"}••••${tok.last4 ?? ""}`;

/** Selects the element's text, so it can be copied by hand when the clipboard is not available. */
function selectText(el: HTMLElement | null) {
  const selection = window.getSelection();
  if (!el || !selection) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);
}

/** The new token's secret, shown once right after it is created. */
function TokenSecret({ secret, onDone }: { secret: string; onDone: () => void }) {
  const t = useTranslations("settings.tokens");
  const demo = useIsDemo();
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const copyButton = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  // The create form is gone; the next thing to do is copy the secret.
  useEffect(() => copyButton.current?.focus(), []);
  // Without clipboard access (an insecure page, a denied permission) the secret is selected for copying by hand.
  const copyByHand = () => {
    selectText(box.current);
    toast(t("copyFailed"), t("copyByHand"), "blocked");
  };
  const copy = () => {
    if (!navigator.clipboard?.writeText) return copyByHand();
    navigator.clipboard.writeText(secret).then(() => setCopied(true), copyByHand);
  };
  return (
    <div className="mt-4 space-y-4">
      <p className="text-sm text-grey-700">{demo ? t("secretDemoNote") : t("secretNote")}</p>
      <div className="flex items-center gap-2">
        <div ref={box} className="min-w-0 flex-1 rounded-md border border-rule bg-grey-50 px-3 py-2 break-all">
          <Id className="text-[12px]">{secret}</Id>
        </div>
        <Button ref={copyButton} variant="secondary" className="h-9 shrink-0" onClick={copy}>
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
      <p aria-live="polite" className="sr-only">
        {copied ? t("copied") : ""}
      </p>
      <div className="flex justify-end">
        <Button onClick={onDone}>{t("done")}</Button>
      </div>
    </div>
  );
}

export function TokensSection() {
  const t = useTranslations("settings.tokens");
  const tc = useTranslations("common");
  const errorText = useErrorText();
  const { ago, date } = useFormat();
  const tokensQuery = useTokens();
  const createToken = useCreateToken();
  const revokeToken = useRevokeToken();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Scope[]>(["agents:read", "runs:read"]);
  const [secret, setSecret] = useState<string | null>(null);
  const toast = useToast();
  const openChange = (next: boolean) => {
    setOpen(next);
    if (!next) setSecret(null);
  };

  const create = () => {
    createToken.mutate(
      { body: { name: name.trim(), scopes } },
      {
        onSuccess: (created) => {
          toast(t("createdToast"), t("createdToastBody"));
          setSecret(created.secret);
          setName("");
          setScopes(["agents:read", "runs:read"]);
        },
        onError: (e) => toast(t("createFailed"), errorText(e), "blocked"),
      },
    );
  };
  const heading = useRef<HTMLHeadingElement>(null);
  const revoke = (token: McpToken, index: number) => {
    revokeToken.mutate(
      { path: { token_id: token.id } },
      {
        onSuccess: () => toast(t("revokedToast"), t("revokedToastBody", { name: token.name })),
        onError: (e) => toast(t("revokeFailed"), errorText(e), "blocked"),
      },
    );
    // The row is gone, so focus the next token's Revoke, or the heading when none are left.
    focusAfterClose(() => {
      const next = heading.current?.closest("section")?.querySelectorAll<HTMLElement>("[data-revoke-token]");
      return sameOrLast(next ?? [], index) ?? heading.current;
    });
  };

  return (
    <Section
      title={t("title")}
      headingRef={heading}
      aside={
        <Modal
          open={open}
          onOpenChange={openChange}
          trigger={
            <Button variant="secondary" className="h-10 sm:h-8">
              {t("create")}
            </Button>
          }
          title={secret ? t("secretTitle") : t("createTitle")}
          description={secret ? undefined : t("createDescription")}
        >
          {secret ? (
            <TokenSecret secret={secret} onDone={() => openChange(false)} />
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim() && scopes.length) create();
              }}
              className="mt-4 space-y-4"
            >
              <label className="block text-sm">
                <span className="font-medium">{t("name")}</span>
                <input
                  name="token-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t("namePlaceholder")}
                  className="mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
                />
              </label>
              <fieldset className="space-y-2.5">
                <legend className="mb-1.5 text-sm font-medium">{t("scopes")}</legend>
                {SCOPES.map((s) => (
                  <Checkbox
                    key={s}
                    checked={scopes.includes(s)}
                    onCheckedChange={(on) => setScopes((cur) => (on ? [...cur, s] : cur.filter((x) => x !== s)))}
                  >
                    {t(`scope.${s}`)} <Id className="ml-1 text-[11px]">{s}</Id>
                  </Checkbox>
                ))}
              </fieldset>
              <div className="flex justify-end gap-2">
                <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
                <Button type="submit" disabled={!name.trim() || scopes.length === 0 || createToken.isPending}>
                  {t("create")}
                </Button>
              </div>
            </form>
          )}
        </Modal>
      }
    >
      <div className="px-5 py-3 text-sm text-grey-700">{t("lede")}</div>
      <QueryState query={tokensQuery} skeleton={<Skeleton className="h-32 rounded-none" />}>
        {(tokens) =>
          tokens.length ? (
            <ul className="divide-y divide-rule border-t border-rule">
              {tokens.map((tok, index) => (
                <li key={tok.id} className="px-5 py-3.5 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{tok.name}</span>
                    <Confirm
                      danger
                      trigger={
                        <button type="button" data-revoke-token className="link text-xs text-blocked">
                          {t("revoke")}
                        </button>
                      }
                      title={t("revokeTitle", { name: tok.name })}
                      description={t("revokeDescription")}
                      confirmLabel={t("revokeConfirm")}
                      onConfirm={() => revoke(tok, index)}
                    />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                    <Id className="text-[11px]">{maskedToken(tok)}</Id>
                    <span>{t("expires", { date: date(tok.expiresAt) })}</span>
                    <span>{tok.lastUsed ? t("lastUsed", { when: ago(tok.lastUsed) }) : t("neverUsed")}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {tok.scopes.map((s) => (
                      <Id key={s} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
                        {s}
                      </Id>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="border-t border-rule px-5 py-4 text-sm text-muted">{t("none")}</p>
          )
        }
      </QueryState>
    </Section>
  );
}
