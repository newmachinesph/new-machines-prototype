"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { Confirm, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, Callout, KeyValues, Section, SimTag } from "@/components/ui";
import type { PublisherProfile } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useMe } from "@/lib/queries/me";
import { isManager } from "@/lib/roles";
import { useDisablePublisher, usePublisher, useSavePublisher } from "@/lib/queries/publisher";

const NAME_MAX = 80;
const DESCRIPTION_MAX = 280;
const PAYOUT_MAX = 200;

const INPUT = "mt-1.5 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink";

function PublisherForm({ initial, orgId, onDone }: { initial?: PublisherProfile; orgId: string; onDone: () => void }) {
  const t = useTranslations("publisherSettings");
  const errorText = useErrorText();
  const toast = useToast();
  const save = useSavePublisher();
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [payoutNote, setPayoutNote] = useState(initial?.payoutNote ?? "");
  const [missingName, setMissingName] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = () => {
    const body = { name: name.trim(), description: description.trim(), payoutNote: payoutNote.trim() };
    if (!body.name) {
      setMissingName(true);
      return;
    }
    setMissingName(false);
    setProblem(null);
    save.mutate(
      { path: { org_id: orgId }, body },
      {
        onSuccess: () => {
          toast(t("savedOn"));
          onDone();
        },
        onError: (e) => setProblem(errorText(e)),
      },
    );
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="space-y-4 px-5 py-4"
      noValidate
    >
      {problem ? <Callout tone="blocked" title={problem} /> : null}
      <div className="text-sm">
        <label htmlFor="publisher-name" className="font-medium">
          {t("name")}
        </label>
        <input
          id="publisher-name"
          name="name"
          value={name}
          maxLength={NAME_MAX}
          onChange={(e) => setName(e.target.value)}
          aria-invalid={missingName}
          aria-describedby={missingName ? "publisher-name-error" : "publisher-name-hint"}
          autoComplete="off"
          className={`${INPUT} h-10`}
        />
        {missingName ? (
          <span id="publisher-name-error" role="alert" className="mt-1 block text-xs text-blocked">
            {t("nameRequired")}
          </span>
        ) : (
          <span id="publisher-name-hint" className="mt-1 block text-xs text-muted">
            {t("nameHint")}
          </span>
        )}
      </div>
      <div className="text-sm">
        <label htmlFor="publisher-description" className="font-medium">
          {t("description")}
        </label>
        <textarea
          id="publisher-description"
          name="description"
          value={description}
          maxLength={DESCRIPTION_MAX}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className={`${INPUT} py-2`}
        />
      </div>
      <div className="text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="publisher-payout" className="font-medium">
            {t("payout")}
          </label>
          <SimTag>{t("simulated")}</SimTag>
        </div>
        <input
          id="publisher-payout"
          aria-describedby="publisher-payout-hint"
          name="payoutNote"
          value={payoutNote}
          maxLength={PAYOUT_MAX}
          onChange={(e) => setPayoutNote(e.target.value)}
          autoComplete="off"
          className={`${INPUT} h-10`}
        />
        <span id="publisher-payout-hint" className="mt-1 block text-xs text-muted">
          {t("payoutHint")}
        </span>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone} disabled={save.isPending}>
          {t("cancel")}
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {t("save")}
        </Button>
      </div>
    </form>
  );
}

export function PublisherSection() {
  const t = useTranslations("publisherSettings");
  const errorText = useErrorText();
  const toast = useToast();
  const me = useMe();
  const publisher = usePublisher();
  const disable = useDisablePublisher();
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const orgId = me.data?.orgId;
  // Only owners and admins see publishing (the API refuses members), so a member has no section at all.
  if (me.data?.workspace !== "live" || orgId === undefined || !isManager(me.data.role)) return null;

  const startEditing = () => {
    setProblem(null);
    setEditing(true);
  };

  const turnOff = () => {
    setProblem(null);
    disable.mutate(
      { path: { org_id: orgId } },
      {
        onSuccess: () => toast(t("savedOff")),
        onError: (e) => setProblem(errorText(e)),
      },
    );
  };

  return (
    <Section title={t("title")}>
      <p className="px-5 pt-4 text-sm text-grey-700">{t("intro")}</p>
      <QueryState query={publisher} skeleton={<Skeleton className="h-32 rounded-none" />} inline>
        {(settings) => {
          const profile = settings.profile;
          const isOn = settings.enabled && profile !== undefined;
          if (editing) {
            return (
              <PublisherForm initial={isOn ? profile : undefined} orgId={orgId} onDone={() => setEditing(false)} />
            );
          }
          return (
            <div className="space-y-4 px-5 py-4">
              {problem ? <Callout tone="blocked" title={problem} /> : null}
              {isOn ? (
                <KeyValues
                  rows={[
                    { label: t("name"), value: profile.name },
                    ...(profile.description ? [{ label: t("description"), value: profile.description }] : []),
                    ...(profile.payoutNote
                      ? [
                          {
                            label: t("payout"),
                            value: (
                              <span className="inline-flex flex-wrap items-center gap-2">
                                {profile.payoutNote} <SimTag>{t("simulated")}</SimTag>
                              </span>
                            ),
                          },
                        ]
                      : []),
                  ]}
                />
              ) : null}
              {!isOn ? <Button onClick={startEditing}>{t("turnOn")}</Button> : null}
              {isOn ? (
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={startEditing}>
                    {t("edit")}
                  </Button>
                  <Confirm
                    danger
                    trigger={
                      <Button variant="ghost" disabled={disable.isPending}>
                        {t("turnOff")}
                      </Button>
                    }
                    title={t("turnOffConfirm")}
                    description={t("turnOffBody")}
                    confirmLabel={t("turnOff")}
                    onConfirm={turnOff}
                  />
                </div>
              ) : null}
            </div>
          );
        }}
      </QueryState>
    </Section>
  );
}
