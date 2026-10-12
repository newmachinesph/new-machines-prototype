"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRef, useState } from "react";
import { Confirm, Modal, ModalClose, focusAfterClose, sameOrLast, useToast } from "@/components/base";
import { ActorGlyph, Button, Callout, Id, Pill, Section } from "@/components/ui";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useErrorText } from "@/lib/api/use-error-text";
import type { MemoryItem } from "@/lib/types";
import { useMemory, useRetractMemory, useReviewMemory } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";

function MemoryCandidate({
  item: m,
  conflict,
  onDecide,
}: {
  item: MemoryItem;
  conflict?: MemoryItem;
  onDecide: () => void;
}) {
  const t = useTranslations("memory.candidate");
  const tc = useTranslations("common");
  const errorText = useErrorText();
  // The outcome comes from the cached item; only the fact that you edited is kept here.
  const [edited, setEdited] = useState(false);
  const outcome = m.state === "APPROVED" ? "approved" : m.state === "REJECTED" ? "rejected" : "open";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(m.text);
  const toast = useToast();
  const review = useReviewMemory();

  const decide = (approved: boolean, text?: string) => {
    onDecide();
    setEdited(approved && text !== undefined && text !== m.text);
    review.mutate(
      { path: { memory_id: m.id }, body: approved ? { decision: "approve", text } : { decision: "reject" } },
      {
        onSuccess: () => {
          if (approved) toast(t("approvedToast"), t("approvedToastBody"));
          else toast(t("rejectedToast"), t("rejectedToastBody"));
        },
        onError: (e) => toast(approved ? t("approveFailed") : t("rejectFailed"), errorText(e), "blocked"),
      },
    );
  };

  return (
    <Section
      title={t("title")}
      aside={
        outcome === "open" ? (
          <Pill tone="human">{t("proposed")}</Pill>
        ) : outcome === "approved" ? (
          <Pill tone="ink">{t("inUse")}</Pill>
        ) : (
          <Pill tone="quiet">{t("rejected")}</Pill>
        )
      }
    >
      <div className="px-5 py-4">
        <blockquote className="border-l-2 border-human pl-4 text-[17px] leading-relaxed">{m.text}</blockquote>
        {edited && outcome === "approved" ? <p className="mt-2 text-xs text-muted">{t("edited")}</p> : null}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          <span className="flex items-center gap-1.5">
            <ActorGlyph actor="human" />
            {t("from", { source: m.source })}
          </span>
          {m.sourceRun ? (
            <Link className="link" href={`/app/runs/${m.sourceRun}`}>
              {m.sourceRun}
            </Link>
          ) : null}
          <span>{t("appliesTo", { name: m.scopeName })}</span>
        </div>
        {conflict ? (
          <div className="mt-4 rounded-[10px] border border-rule bg-stage px-4 py-3 text-sm">
            <div className="font-medium">{t("conflict")}</div>
            <p className="mt-1 text-grey-700">“{conflict.text}”</p>
            <p className="mt-1 text-xs text-muted">
              {t.rich("conflictNote", {
                id: conflict.id,
                mono: (chunks) => <Id className="text-[11px]">{chunks}</Id>,
              })}
            </p>
          </div>
        ) : null}
        <p className="mt-4 text-sm text-muted">
          {t.rich("pendingNote", {
            run: (chunks) => (
              <Link className="link" href="/app/runs/run_1047">
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
      <div className="border-t border-rule px-5 py-3.5">
        {outcome === "open" ? (
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" disabled={review.isPending} onClick={() => decide(false)}>
              {t("reject")}
            </Button>
            <Modal
              open={editing}
              onOpenChange={(o) => {
                setEditing(o);
                if (o) setDraft(m.text);
              }}
              trigger={<Button variant="secondary">{t("edit")}</Button>}
              title={t("edit")}
              description={t("editDescription")}
            >
              <label htmlFor="mem-draft" className="sr-only">
                {t("textLabel")}
              </label>
              <textarea
                id="mem-draft"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={4}
                className="mt-4 w-full rounded-md border border-grey-300 px-3 py-2 text-sm leading-relaxed outline-none focus:border-ink"
              />
              <div className="mt-4 flex justify-end gap-2">
                <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
                <Button
                  disabled={draft.trim().length < 10 || review.isPending}
                  onClick={() => {
                    setEditing(false);
                    decide(true, draft.trim());
                  }}
                >
                  {t("approveEdited")}
                </Button>
              </div>
            </Modal>
            <Button disabled={review.isPending} onClick={() => decide(true)}>
              {t("approve")}
            </Button>
          </div>
        ) : outcome === "approved" ? (
          <Callout tone="info" title={t("approvedTitle")}>
            {t("approvedBody")}
          </Callout>
        ) : (
          <Callout tone="warn" title={t("rejectedTitle")}>
            {t("rejectedBody")}
          </Callout>
        )}
      </div>
    </Section>
  );
}

const STATE_TONE: Record<MemoryItem["state"] | "RETRACTED", "human" | "ink" | "quiet"> = {
  CANDIDATE: "human",
  APPROVED: "ink",
  CORRECTED: "quiet",
  REJECTED: "quiet",
  EXPIRED: "quiet",
  CONTRADICTION: "human",
  RETRACTED: "quiet",
};

type Row = MemoryItem;

function MemoryRow({ item: m, onRetract }: { item: Row; onRetract?: () => void }) {
  const t = useTranslations("memory.row");
  const { dateTime } = useFormat();
  const state = m.retracted ? "RETRACTED" : m.state;
  return (
    <li className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="text-sm">{m.text}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
          <span>{t("scopeLine", { scope: t(`scope.${m.scope}`), name: m.scopeName })}</span>
          <span>{m.source}</span>
          <span>{dateTime(m.createdAt)}</span>
          {m.usedIn ? <span>{t("usedIn", { n: m.usedIn })}</span> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Pill tone={STATE_TONE[state]}>{t(`state.${state}`)}</Pill>
        {onRetract ? (
          <Confirm
            trigger={
              <button type="button" data-retract className="link text-xs text-muted">
                {t("retract")}
              </button>
            }
            title={t("retractTitle")}
            description={t("retractDescription")}
            confirmLabel={t("retractConfirm")}
            onConfirm={onRetract}
          />
        ) : null}
      </div>
    </li>
  );
}

export function MemoryBoard() {
  const memory = useMemory();
  return (
    <QueryState query={memory} skeleton={<Skeleton className="h-96" />}>
      {(rows) => <MemoryColumns rows={rows} />}
    </QueryState>
  );
}

function MemoryColumns({ rows }: { rows: Row[] }) {
  const t = useTranslations("memory");
  const errorText = useErrorText();
  const retractMemory = useRetractMemory();
  const toast = useToast();
  // A candidate you just decided stays on screen with its outcome instead of leaving the list.
  const [decided, setDecided] = useState<string[]>([]);
  const candidates = rows.filter((m) => m.state === "CANDIDATE" || decided.includes(m.id));
  const inUse = rows.filter((m) => m.state === "APPROVED" && !m.retracted);
  const past = rows.filter((m) => m.state !== "CANDIDATE" && (m.state !== "APPROVED" || m.retracted));

  const inUseHeading = useRef<HTMLHeadingElement>(null);
  const retract = (id: string) => {
    const index = inUse.findIndex((m) => m.id === id);
    retractMemory.mutate(
      { path: { memory_id: id } },
      {
        onSuccess: () => toast(t("retractedToast"), t("retractedToastBody")),
        onError: (e) => toast(t("retractFailed"), errorText(e), "blocked"),
      },
    );
    // The row leaves this list, so focus the next memory's Retract, or the heading once the list is empty.
    focusAfterClose(() => {
      const next = inUseHeading.current?.closest("section")?.querySelectorAll<HTMLElement>("[data-retract]");
      return sameOrLast(next ?? [], index) ?? inUseHeading.current;
    });
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
      <div className="space-y-6 xl:sticky xl:top-20">
        {candidates.map((m) => (
          <MemoryCandidate
            key={m.id}
            item={m}
            conflict={rows.find((x) => x.id === m.conflictsWith)}
            onDecide={() => setDecided((ids) => (ids.includes(m.id) ? ids : [...ids, m.id]))}
          />
        ))}
      </div>
      <div className="space-y-6">
        <Section
          title={t("inUse")}
          headingRef={inUseHeading}
          aside={<span className="text-xs text-muted">{t("count", { n: inUse.length })}</span>}
        >
          {inUse.length ? (
            <ul className="divide-y divide-rule">
              {inUse.map((m) => (
                <MemoryRow key={m.id} item={m} onRetract={() => retract(m.id)} />
              ))}
            </ul>
          ) : (
            <p className="px-5 py-6 text-sm text-muted">{t("none")}</p>
          )}
        </Section>
        <Section title={t("past")}>
          <ul className="divide-y divide-rule">
            {past.map((m) => (
              <MemoryRow key={m.id} item={m} />
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}
