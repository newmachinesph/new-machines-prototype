"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useId, useRef, useState } from "react";
import { Confirm, Modal, ModalClose, Select, focusAfterClose, sameOrLast, useToast } from "@/components/base";
import { ActorGlyph, Button, ButtonLink, Callout, EmptyState, Id, Pill, Section } from "@/components/ui";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useErrorText } from "@/lib/api/use-error-text";
import { SEED_SOURCE, useSeedText, useSpaceName } from "@/lib/content-text";
import type { MemoryItem } from "@/lib/types";
import { useMe } from "@/lib/queries/me";
import { useAddMemory, useMemory, useMemorySpaces, useRetractMemory, useReviewMemory } from "@/lib/queries/workspace";
import { isManager } from "@/lib/roles";
import { useFormat } from "@/lib/use-format";

/** The API's source labels as whole phrases; a run's label ("Run run_2011") becomes "From run 2011". */
const SOURCE_KEYS = { [SEED_SOURCE]: "seed", "New Machines": "console", "Your team": "team" } as const;
const RUN_SOURCE = /^Run (run_(\w+))$/;
/** The API's limit on a memory's text. */
const TEXT_MAX = 2000;

function useSourceLabel() {
  const t = useTranslations("memory.source");
  return (source: string) => {
    const key = SOURCE_KEYS[source as keyof typeof SOURCE_KEYS];
    if (key) return t(key);
    const run = RUN_SOURCE.exec(source);
    return run ? t("run", { n: run[2] }) : t("other", { source });
  };
}

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
  const sourceLabel = useSourceLabel();
  const spaceName = useSpaceName();
  const seedText = useSeedText();
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
            {m.sourceRun ? (
              <Link className="link" href={`/app/runs/${m.sourceRun}`}>
                {sourceLabel(m.source)}
              </Link>
            ) : (
              sourceLabel(m.source)
            )}
          </span>
          <span>{t("appliesTo", { name: spaceName(m.scopeName) })}</span>
        </div>
        {conflict ? (
          <div className="mt-4 rounded-[10px] border border-rule bg-stage px-4 py-3 text-sm">
            <div className="font-medium">{t("conflict")}</div>
            <p className="mt-1 text-grey-700">“{seedText(conflict)}”</p>
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
  const sourceLabel = useSourceLabel();
  const spaceName = useSpaceName();
  const seedText = useSeedText();
  const { dateTime } = useFormat();
  const state = m.retracted ? "RETRACTED" : m.state;
  return (
    <li className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        {/* A seed that comes with one of our packs reads in the interface language; anything else as stored. */}
        <p className="text-sm">{seedText(m)}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
          <span>{t("appliesTo", { name: spaceName(m.scopeName) })}</span>
          <span>{sourceLabel(m.source)}</span>
          <span>{dateTime(m.createdAt)}</span>
          {m.usedIn ? <span>{t("usedIn", { n: m.usedIn })}</span> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Pill tone={STATE_TONE[state]}>{t(`state.${state}`)}</Pill>
        {onRetract ? (
          <Confirm
            danger
            trigger={
              <Button variant="danger" className="h-10 sm:h-8" data-retract>
                {t("retract")}
              </Button>
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

/** An owner or admin tells the agents something: one rule, in one of the spaces the workspace reads. */
function AddMemory() {
  const t = useTranslations("memory.add");
  const tc = useTranslations("common");
  const toast = useToast();
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [space, setSpace] = useState("");
  const [text, setText] = useState("");
  const spaces = useMemorySpaces(open);
  const spaceName = useSpaceName();
  const add = useAddMemory();
  const items = (spaces.data ?? []).map((s) => ({ value: s.id, label: spaceName(s.name, s.id) }));
  // The first space applies until a person picks another.
  const chosen = items.some((s) => s.value === space) ? space : (items[0]?.value ?? "");
  const trimmed = text.trim();
  const valid = chosen !== "" && trimmed.length > 0 && trimmed.length <= TEXT_MAX;
  const atLimit = text.length >= TEXT_MAX;
  const countId = useId();
  const spacesNoteId = useId();
  const textField = useRef<HTMLTextAreaElement>(null);
  // What the space field says about its list: failed, still loading, or nothing to choose from.
  const spacesNote = spaces.isError
    ? t("spacesFailed")
    : spaces.isPending
      ? t("spacesLoading")
      : items.length
        ? null
        : t("noSpaces");

  // Closing starts the next memory afresh.
  const close = () => {
    setOpen(false);
    setText("");
    setSpace("");
  };
  // Cancel, Escape, the X and a click outside close it. Closed while the memory is still being saved, the draft is
  // kept: a save that then fails is reported by its toast, and reopening brings the text back to retry.
  const change = (o: boolean) => {
    if (o) setOpen(true);
    else if (add.isPending) setOpen(false);
    else close();
  };

  const submit = () => {
    add.mutate(
      { body: { space: chosen, text: trimmed } },
      {
        onSuccess: () => {
          toast(t("addedToast"), t("addedToastBody"));
          close();
        },
        onError: (e) => {
          toast(t("addFailed"), errorText(e), "blocked");
          // Back to the text to try again (when the dialog is still open).
          focusAfterClose(() => textField.current);
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onOpenChange={change}
      trigger={
        <Button variant="secondary" className="h-10 sm:h-8">
          {t("action")}
        </Button>
      }
      title={t("title")}
      description={t("description")}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) submit();
        }}
        aria-busy={add.isPending}
        className="mt-4"
      >
        {/* Nothing changes under a person's hands while the memory is being saved. */}
        <fieldset disabled={add.isPending} className="space-y-4">
          <div>
            <label htmlFor="mem-space" className="mb-1.5 block text-sm font-medium">
              {t("space")}
            </label>
            <Select
              id="mem-space"
              label={t("space")}
              value={chosen}
              onValueChange={setSpace}
              items={items}
              disabled={!items.length || add.isPending}
              invalid={spaces.isError}
              describedBy={spacesNote ? spacesNoteId : undefined}
              className="w-full"
            />
            {spacesNote ? (
              <p
                id={spacesNoteId}
                role={spaces.isError ? "alert" : "status"}
                className={`mt-1.5 text-xs ${spaces.isError ? "text-blocked" : "text-muted"}`}
              >
                {spacesNote}
              </p>
            ) : null}
          </div>
          <div>
            <label htmlFor="mem-text" className="mb-1.5 block text-sm font-medium">
              {t("text")}
            </label>
            <textarea
              id="mem-text"
              ref={textField}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              maxLength={TEXT_MAX}
              placeholder={t("textPlaceholder")}
              aria-describedby={countId}
              className="w-full rounded-md border border-grey-300 px-3 py-2 text-sm leading-relaxed outline-none focus:border-ink"
            />
            <p id={countId} className="mt-1.5 text-xs text-muted">
              {t("count", { n: text.length, max: TEXT_MAX })}
            </p>
            {/* Always in the tree, so the limit is announced the moment it is reached. */}
            <p aria-live="polite" className={atLimit ? "mt-1 text-xs text-muted" : "sr-only"}>
              {atLimit ? t("atLimit") : ""}
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
            <Button type="submit" disabled={!valid || add.isPending}>
              {add.isPending ? t("saving") : t("save")}
            </Button>
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}

/** A memory an owner or admin added by hand (the API labels its source "Your team"). */
const isTeamMemory = (m: Row) => SOURCE_KEYS[m.source as keyof typeof SOURCE_KEYS] === "team";

export function MemoryBoard() {
  const memory = useMemory();
  // Owners and admins add memories and retract what the team added (the API's `require_manager`).
  const canManage = isManager(useMe().data?.role);
  return (
    <>
      {/* Above the lists, whatever they hold, so the trigger keeps focus after a memory is added. */}
      {canManage ? (
        <div className="mb-4 flex justify-end">
          <AddMemory />
        </div>
      ) : null}
      <QueryState query={memory} skeleton={<Skeleton className="h-96" />}>
        {(rows) => (rows.length ? <MemoryColumns rows={rows} canManage={canManage} /> : <NoMemory />)}
      </QueryState>
    </>
  );
}

/** Nothing learned yet. */
function NoMemory() {
  const t = useTranslations("memory");
  return (
    <div className="panel">
      <EmptyState
        action={
          <ButtonLink href="/app/runs" variant="secondary" className="h-10 sm:h-8">
            {t("seeRuns")}
          </ButtonLink>
        }
      >
        {t("empty")}
      </EmptyState>
    </div>
  );
}

function MemoryColumns({ rows, canManage }: { rows: Row[]; canManage: boolean }) {
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
        {candidates.length ? null : (
          <Section title={t("candidate.title")}>
            <p className="px-5 py-6 text-sm text-muted">{t("noCandidates")}</p>
          </Section>
        )}
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
                <MemoryRow
                  key={m.id}
                  item={m}
                  // Only an owner or admin retracts what the team added; a run's items keep today's rule.
                  onRetract={canManage || !isTeamMemory(m) ? () => retract(m.id) : undefined}
                />
              ))}
            </ul>
          ) : (
            <p className="px-5 py-6 text-sm text-muted">{t("none")}</p>
          )}
        </Section>
        {past.length ? (
          <Section title={t("past")}>
            <ul className="divide-y divide-rule">
              {past.map((m) => (
                <MemoryRow key={m.id} item={m} />
              ))}
            </ul>
          </Section>
        ) : null}
      </div>
    </div>
  );
}
