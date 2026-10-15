"use client";

import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { Checkbox, Confirm, focusAfterClose, Modal, ModalClose, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, EmptyState, Pill, Section, SimTag } from "@/components/ui";
import type { OrgReviewer } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useMe, useOrgId } from "@/lib/queries/me";
import { useAddReviewer, useOrgReviewers, useRemoveReviewer, useSetReviewerNetwork } from "@/lib/queries/reviewers";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MANAGERS = new Set(["owner", "admin"]);

export function ReviewersView() {
  const t = useTranslations("reviewers");
  const me = useMe();
  const query = useOrgReviewers();
  if (me.data && me.data.workspace !== "live") {
    return (
      <div className="panel">
        <EmptyState>{t("liveOnly")}</EmptyState>
      </div>
    );
  }
  const canManage = MANAGERS.has(me.data?.role ?? "");
  return (
    <QueryState query={query} skeleton={<Skeleton className="h-64" />}>
      {(data) => (
        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <TeamSection reviewers={data.reviewers} canManage={canManage} myEmail={me.data?.email} />
          <NetworkSection allow={data.allowNetwork} canManage={canManage} />
        </div>
      )}
    </QueryState>
  );
}

function AddReviewer() {
  const t = useTranslations("reviewers");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorText = useErrorText();
  const orgId = useOrgId();
  const add = useAddReviewer();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const address = email.trim();
  const wellFormed = EMAIL.test(address);
  const valid = wellFormed && orgId !== undefined;
  // Flag the address once something is typed, never an empty field that was just opened.
  const invalid = address !== "" && !wellFormed;
  const hintId = useId();

  const submit = () => {
    if (!orgId) return;
    add.mutate(
      { path: { org_id: orgId }, body: { email: address } },
      {
        onSuccess: (r) => {
          toast(t("added"), t(r.pending ? "addedPending" : "addedMember", { address: r.email }));
          setOpen(false);
          setEmail("");
        },
        onError: (e) => toast(t("addFailed"), errorText(e), "blocked"),
      },
    );
  };

  return (
    <Modal
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button variant="secondary" className="h-10 sm:h-8">
          {t("add")}
        </Button>
      }
      title={t("addTitle")}
      description={t("addDescription")}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) submit();
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
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? hintId : undefined}
            className="mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
          />
          {invalid ? (
            <span id={hintId} className="mt-1.5 block text-xs text-muted">
              {t("emailInvalid")}
            </span>
          ) : null}
        </label>
        <div className="flex justify-end gap-2">
          <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
          <Button type="submit" disabled={!valid || add.isPending}>
            {t("send")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function TeamSection({
  reviewers,
  canManage,
  myEmail,
}: {
  reviewers: OrgReviewer[];
  canManage: boolean;
  myEmail?: string;
}) {
  const t = useTranslations("reviewers");
  const tn = useTranslations("nav");
  const toast = useToast();
  const errorText = useErrorText();
  const orgId = useOrgId();
  const remove = useRemoveReviewer();
  const heading = useRef<HTMLHeadingElement>(null);
  // Removing only clears the reviewer flag (an owner or admin keeps their role), so everyone can be removed.
  // Wait for who "me" is, so the self wording never flashes in late.
  const mine = myEmail?.toLowerCase();
  const isMe = (r: OrgReviewer) => r.email.toLowerCase() === mine;

  const drop = (r: OrgReviewer) => {
    if (!orgId) return;
    remove.mutate(
      { path: { org_id: orgId }, body: { email: r.email } },
      {
        onSuccess: () => {
          toast(t("removed"));
          // The row and its Remove button go with the refetch; the heading stays, so focus never drops to body.
          focusAfterClose(() => heading.current);
        },
        onError: (e) => toast(t("removeFailed"), errorText(e), "blocked"),
      },
    );
  };

  return (
    <Section title={t("team")} headingRef={heading} aside={canManage ? <AddReviewer /> : null}>
      {reviewers.length === 0 ? (
        <EmptyState>{t("empty")}</EmptyState>
      ) : (
        <ul className="divide-y divide-rule">
          {reviewers.map((r) => (
            <li key={r.email} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
              <div className="min-w-0">
                <div className="truncate font-medium">{r.name}</div>
                <div className="text-xs text-muted">{r.pending ? t("pendingNote") : r.email}</div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                {r.pending ? (
                  <Pill tone="quiet">{t("pending")}</Pill>
                ) : (
                  <span className="text-grey-700">{tn(`roles.${r.role}`)}</span>
                )}
                {canManage && mine ? (
                  <Confirm
                    danger
                    trigger={
                      <Button variant="danger" className="h-10 sm:h-8" aria-label={t("removeLabel", { name: r.name })}>
                        {t("remove")}
                      </Button>
                    }
                    title={isMe(r) ? t("removeSelfTitle") : t("removeTitle", { name: r.name })}
                    description={isMe(r) ? t("removeSelfDescription") : t("removeDescription")}
                    confirmLabel={t("removeConfirm")}
                    onConfirm={() => drop(r)}
                  />
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {canManage ? null : <p className="border-t border-rule px-5 py-3 text-xs text-muted">{t("managersOnly")}</p>}
    </Section>
  );
}

function NetworkSection({ allow, canManage }: { allow: boolean; canManage: boolean }) {
  const t = useTranslations("reviewers");
  const toast = useToast();
  const errorText = useErrorText();
  const orgId = useOrgId();
  const setNetwork = useSetReviewerNetwork();
  const [confirmOff, setConfirmOff] = useState(false);

  const save = (next: boolean) => {
    if (!orgId) return;
    setNetwork.mutate(
      { path: { org_id: orgId }, body: { allow: next } },
      {
        onSuccess: (r) => toast(r.allowNetwork ? t("networkOn") : t("networkOff")),
        onError: (e) => toast(t("networkFailed"), errorText(e), "blocked"),
      },
    );
  };
  // Allowing is one click. Turning off returns network reviewers' claimed tasks to the queue, so it asks first;
  // the box stays ticked until the answer comes back.
  const change = (next: boolean) => (next ? save(true) : setConfirmOff(true));

  return (
    <Section title={t("network")}>
      <div className="space-y-3 px-5 py-4 text-sm">
        {canManage ? (
          <>
            <Checkbox checked={allow} onCheckedChange={change}>
              {t("allowNetwork")}
            </Checkbox>
            <Confirm
              open={confirmOff}
              onOpenChange={setConfirmOff}
              danger
              title={t("networkOffTitle")}
              description={t("networkOffDescription")}
              confirmLabel={t("networkOffConfirm")}
              onConfirm={() => save(false)}
            />
          </>
        ) : (
          <p className="font-medium">{allow ? t("networkIsOn") : t("networkIsOff")}</p>
        )}
        <p className="text-muted">{t("allowNetworkNote")}</p>
        <SimTag className="px-2 py-1 text-xs">{t("networkPay")}</SimTag>
      </div>
    </Section>
  );
}
