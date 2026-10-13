"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Choices, focusAfterClose, useToast } from "@/components/base";
import { Amount, Button, ButtonLink, Callout, Id, KeyValues, Pill, Section, SimTag } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useErrorText } from "@/lib/api/use-error-text";
import { utc, WORKER_TZ } from "@/lib/format";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { useFormat } from "@/lib/use-format";
import { useClaimTask, useSubmitReview } from "@/lib/queries/tasks";
import type { HumanTask, RedactedRecord, ReviewVerdict } from "@/lib/types";

type Phase = "offer" | "claimed" | "expired" | "validating" | "submitted" | "accepted" | "closed";
type Call = "match" | "mismatch" | "pending";
type Review = { verdict: ReviewVerdict; feedbackText: string; recordCalls: Record<string, Call> };

const VERDICTS: ReviewVerdict[] = ["APPROVED", "REVISION_REQUIRED", "REJECTED", "ESCALATED"];
/** On a real run, these verdicts stop the run instead of sending it on. */
const STOPPING: ReviewVerdict[] = ["REJECTED", "ESCALATED"];

type RunOutcome = NonNullable<HumanTask["runOutcome"]>;

// Under this many seconds the hold timer turns to a warning.
const LEASE_WARN_SECONDS = 5 * 60;
const MAX_LEASE_OVERRIDE_SECONDS = 24 * 60 * 60;

/**
 * Seconds a fresh hold lasts. For demos, `?lease=5` overrides the task's lease in seconds so
 * expiry can be seen without waiting. Read at claim time so the page stays statically rendered.
 */
function startingLease(task: HumanTask): number {
  const override = Number(new URLSearchParams(window.location.search).get("lease"));
  return Number.isInteger(override) && override > 0 && override <= MAX_LEASE_OVERRIDE_SECONDS
    ? override
    : task.leaseMinutes * 60;
}

// Where the page opens depends on what the server already knows about the task.
function openingPhase(task: HumanTask): Phase {
  switch (task.state) {
    case "CLAIMED":
      return "claimed";
    case "OFFERED":
    case "EXPIRED":
      return "offer";
    case "ACCEPTED":
      return "accepted";
    case "SUBMITTED":
    case "VALIDATING":
      return "submitted";
    default:
      return "closed";
  }
}

export function TaskWorkspace({ task, buyer }: { task: HumanTask; buyer: string }) {
  const t = useTranslations("task");
  const { money } = useFormat();
  const errorText = useErrorText();
  const toast = useToast();
  const claimTask = useClaimTask();
  const submitReview = useSubmitReview();
  const [phase, setPhase] = useState<Phase>(() => openingPhase(task));
  // A real run's task has no acceptance check: the verdict goes straight to the run, which goes on or stops.
  const realRun = Boolean(task.realRun);
  const [runOutcome, setRunOutcome] = useState<RunOutcome | undefined>(task.runOutcome ?? undefined);
  // The API has no lease end, so only a claim made in this session gets a precise countdown.
  const [timed, setTimed] = useState(false);
  const [leaseEnd, setLeaseEnd] = useState(0);
  const [left, setLeft] = useState(0);
  // Warn only when the countdown crosses the threshold, not when a short hold starts below it.
  const [startedAbove, setStartedAbove] = useState(false);
  const claimButton = useRef<HTMLButtonElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const claimAgainButton = useRef<HTMLButtonElement>(null);
  const tWork = useTranslations("work");
  const interactive = task.records.length > 0;
  const holding = phase === "claimed" || phase === "expired";

  useEffect(() => {
    // The check after a submit made in this session is simulated: the API only records SUBMITTED.
    if (phase !== "validating") return;
    const timer = setTimeout(() => setPhase("accepted"), 1400);
    return () => clearTimeout(timer);
  }, [phase]);

  // The hold counts down against a fixed end time and stops at zero, which ends the claim.
  useEffect(() => {
    if (phase !== "claimed" || !timed) return;
    const timer = setInterval(() => {
      const s = Math.max(0, Math.ceil((leaseEnd - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) setPhase("expired");
    }, 250);
    return () => clearInterval(timer);
  }, [phase, timed, leaseEnd]);

  // Expiry disables Submit; if focus was on it (or anywhere in the task), hand it to Claim again.
  useEffect(() => {
    if (phase !== "expired") return;
    const active = document.activeElement;
    if (active === document.body || root.current?.contains(active)) claimAgainButton.current?.focus();
  }, [phase]);

  const claim = (onClaimed: (() => void) | undefined, button: React.RefObject<HTMLButtonElement | null>) =>
    claimTask.mutate(
      { path: { task_id: task.id } },
      {
        onSuccess: () => {
          const seconds = startingLease(task);
          setLeaseEnd(Date.now() + seconds * 1000);
          setLeft(seconds);
          setStartedAbove(seconds > LEASE_WARN_SECONDS);
          setTimed(true);
          setPhase("claimed");
          onClaimed?.();
        },
        onError: (e) => {
          toast(t("offer.claimFailed"), errorText(e), "blocked");
          button.current?.focus();
        },
      },
    );
  // The banner holding this button goes away, so keep focus on the page instead of the body.
  const claimAgain = () => claim(() => focusAfterClose(() => title.current), claimAgainButton);
  const submit = (review: Review) =>
    submitReview.mutate(
      { path: { task_id: task.id }, body: review },
      {
        onSuccess: (updated) => {
          if (!realRun) return setPhase("validating");
          setRunOutcome(updated?.runOutcome ?? (STOPPING.includes(review.verdict) ? "STOPS" : "CONTINUES"));
          setPhase("submitted");
        },
        onError: (e) => toast(t("feedback.submitFailed"), errorText(e), "blocked"),
      },
    );

  return (
    <div ref={root} className="space-y-6">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 ref={title} tabIndex={-1} className="h-page outline-none">
            {task.title}
          </h1>
          <p className="mt-1.5 text-[15px] text-muted">{t("byline", { buyer, pack: task.packName })}</p>
        </div>
        <div className="flex items-center gap-4">
          {holding && timed ? <LeaseTimer seconds={left} /> : null}
          <div className="text-right">
            <Amount value={task.pay} className="block text-2xl font-semibold tracking-tight" />
            <span className="text-xs text-muted">{t("simulatedPay", { terms: task.payTerms })}</span>
          </div>
        </div>
      </header>

      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {phase === "expired"
          ? t("holdRanOutLive")
          : phase === "claimed" && timed && startedAbove && left < LEASE_WARN_SECONDS
            ? t("lessThanFive")
            : ""}
      </div>

      {phase === "offer" ? (
        <Offer
          task={task}
          interactive={interactive}
          claiming={claimTask.isPending}
          onClaim={() => claim(undefined, claimButton)}
          buttonRef={claimButton}
        />
      ) : null}
      {phase === "expired" ? (
        <Callout
          tone="blocked"
          announce={false}
          title={t("expired.title")}
          action={
            <div className="flex flex-wrap gap-2">
              <Button ref={claimAgainButton} onClick={claimAgain} disabled={claimTask.isPending}>
                {t("expired.claimAgain")}
              </Button>
              <ButtonLink href="/work" variant="secondary">
                {tWork("backToTasks")}
              </ButtonLink>
            </div>
          }
        >
          {t("expired.body")}
        </Callout>
      ) : null}
      {phase === "claimed" && !timed ? (
        <Callout tone="info" title={t("claimed.title")}>
          {t("claimed.body", { n: task.leaseMinutes })}
        </Callout>
      ) : null}
      {phase === "closed" ? (
        <Callout tone="info" title={t("closed.title")}>
          {t("closed.body")}{" "}
          <Link className="link" href="/work">
            {tWork("backToTasks")}
          </Link>
        </Callout>
      ) : null}
      {holding ? (
        <Workspace
          task={task}
          realRun={realRun}
          expired={phase === "expired"}
          submitting={submitReview.isPending}
          onSubmit={submit}
        />
      ) : null}
      {phase === "validating" ? (
        <Callout tone="info" title={t("validating.title")}>
          {t("validating.body")} <SimTag>{t("validating.simulatedCheck")}</SimTag>
        </Callout>
      ) : null}
      {phase === "submitted" && realRun ? <RunSubmitted outcome={runOutcome} /> : null}
      {phase === "submitted" && !realRun && task.state !== "ACCEPTED" ? (
        <Callout tone="info" title={t("submitted.title")}>
          {t("submitted.body")}{" "}
          <Link className="link" href="/work">
            {tWork("backToTasks")}
          </Link>
        </Callout>
      ) : null}
      {phase === "accepted" || (phase === "submitted" && task.state === "ACCEPTED") ? (
        <div className="space-y-4">
          <Callout
            tone="info"
            title={t("accepted.title", { pay: money(task.pay) })}
            action={
              <ButtonLink href="/work/earnings" variant="secondary">
                {tWork("seeEarnings")}
              </ButtonLink>
            }
          >
            {t("accepted.body")}
          </Callout>
          <p className="text-sm text-muted">
            {t.rich("accepted.runNote", {
              id: task.runId,
              run: (chunks) => (
                <Link className="link" href={`/app/runs/${task.runId}`}>
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </div>
      ) : null}
    </div>
  );
}

/** A submitted review on a real run: what the run does with it. Unknown outcome (an older answer): just recorded. */
function RunSubmitted({ outcome }: { outcome?: RunOutcome }) {
  const t = useTranslations("task.runSubmitted");
  const tWork = useTranslations("work");
  const key = outcome === "STOPS" ? "stops" : outcome === "CONTINUES" ? "continues" : "recorded";
  return (
    <Callout tone={outcome === "STOPS" ? "warn" : "info"} title={t(`${key}Title`)}>
      {t(`${key}Body`)}{" "}
      <Link className="link" href="/work">
        {tWork("backToTasks")}
      </Link>
    </Callout>
  );
}

function Offer({
  task,
  interactive,
  claiming,
  onClaim,
  buttonRef,
}: {
  task: HumanTask;
  interactive: boolean;
  claiming: boolean;
  onClaim: () => void;
  buttonRef: React.Ref<HTMLButtonElement>;
}) {
  const t = useTranslations("task.offer");
  const tWork = useTranslations("work");
  const { dateTime, until, list } = useFormat();
  const regions = useRegionNames();
  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <Section title={t("before")}>
        <div className="px-5 py-2">
          <KeyValues
            rows={[
              { label: t("willDo"), value: task.question },
              { label: t("skill"), value: task.skill },
              { label: t("time"), value: t("timeValue", { est: task.estMinutes, lease: task.leaseMinutes }) },
              {
                label: t("due"),
                value: tWork("due", {
                  when: dateTime(task.deadline, WORKER_TZ),
                  utc: utc(task.deadline),
                  until: until(task.deadline),
                }),
              },
              {
                label: t("data"),
                value: task.dataClass === "CONFIDENTIAL" ? t("dataConfidential") : t("dataProduct"),
              },
              { label: t("openTo"), value: list(task.regions.map(regions)) },
            ]}
          />
        </div>
      </Section>
      <div className="space-y-6">
        <Section title={t("obligations")}>
          <ul className="list-disc space-y-1.5 py-4 pr-5 pl-9 text-sm text-grey-700">
            {task.obligations.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </Section>
        <div className="panel p-5">
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted">{t("willBePaid")}</span>
            <Amount value={task.pay} className="text-lg font-semibold" />
          </div>
          <p className="mt-1 text-xs text-muted">{t("owedNote")}</p>
          <Button ref={buttonRef} className="mt-4 w-full" onClick={onClaim} disabled={!interactive || claiming}>
            {t("claim")}
          </Button>
          {!interactive ? <p className="mt-2 text-xs text-muted">{t("demoOnly")}</p> : null}
        </div>
      </div>
    </div>
  );
}

/** Country names in the interface language, falling back to the code for anything the runtime does not know. */
function useRegionNames() {
  const tag = INTL_TAGS[resolveLocale(useLocale())];
  const names = useMemo(() => new Intl.DisplayNames(tag, { type: "region" }), [tag]);
  return (code: string) => {
    try {
      return names.of(code) ?? code;
    } catch {
      return code;
    }
  };
}

function LeaseTimer({ seconds }: { seconds: number }) {
  const t = useTranslations("task.lease");
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  const ended = seconds === 0;
  const warn = seconds < LEASE_WARN_SECONDS;
  return (
    <div
      role="timer"
      aria-label={ended ? t("endedLabel") : t("label", { mm, ss })}
      className={cn(
        "rounded-md border px-3 py-1.5 text-right",
        warn ? "border-blocked/40 bg-blocked-soft/60 text-blocked" : "border-human/40 bg-human-soft/60 text-human",
      )}
    >
      <div className="tnum font-mono text-base font-semibold">
        {mm}:{ss}
      </div>
      <div className="text-[11px]">{ended ? t("ended") : warn ? t("warn") : t("left")}</div>
    </div>
  );
}

function Workspace({
  task,
  realRun,
  expired,
  submitting,
  onSubmit,
}: {
  task: HumanTask;
  realRun: boolean;
  expired: boolean;
  submitting: boolean;
  onSubmit: (review: Review) => void;
}) {
  const t = useTranslations("task");
  const [calls, setCalls] = useState<Record<string, Call | undefined>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [verdict, setVerdict] = useState<ReviewVerdict>("REVISION_REQUIRED");
  const [feedback, setFeedback] = useState("");
  const complete = task.records.every((r) => calls[r.id]) && feedback.trim().length >= 10;

  const send = () => {
    const recordCalls: Record<string, Call> = {};
    for (const r of task.records) {
      const call = calls[r.id];
      if (call) recordCalls[r.id] = call;
    }
    // The general note comes first, then each record's correction.
    const feedbackText = [feedback, ...task.records.map((r) => notes[r.id] ?? "")]
      .map((part) => part.trim())
      .filter(Boolean)
      .join("\n\n");
    onSubmit({ verdict, feedbackText, recordCalls });
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <p className="max-w-[78ch] text-sm leading-relaxed text-grey-700">{task.instructions}</p>
        {task.records.map((r, i) => (
          <RecordCard
            key={r.id}
            index={i + 1}
            total={task.records.length}
            record={r}
            call={calls[r.id]}
            note={notes[r.id] ?? ""}
            onCall={(c) => setCalls({ ...calls, [r.id]: c })}
            onNote={(n) => setNotes({ ...notes, [r.id]: n })}
          />
        ))}
      </div>
      <Section title={t("verdict.title")} className="xl:sticky xl:top-20">
        <div className="px-5 py-4">
          <Choices
            label={t("verdict.label")}
            value={verdict}
            onValueChange={setVerdict}
            options={VERDICTS.map((v) => ({
              value: v,
              label: t(`verdict.${v}.label`),
              description: realRun && v !== "APPROVED" ? t(`verdict.${v}.helpRun`) : t(`verdict.${v}.help`),
            }))}
          />
        </div>
        <div className="border-t border-rule px-5 py-4">
          <label htmlFor="feedback" className="text-sm font-medium">
            {t("feedback.label")}
          </label>
          <p className="text-xs text-muted">{t("feedback.help")}</p>
          <textarea
            id="feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={5}
            placeholder={t("feedback.placeholder")}
            className="mt-2 w-full rounded-md border border-grey-300 px-3 py-2 text-sm outline-none focus:border-ink"
          />
          <Button className="mt-3 w-full" disabled={!complete || expired || submitting} onClick={send}>
            {t("feedback.submit")}
          </Button>
          {expired ? (
            <p className="mt-2 text-xs text-blocked">{t("feedback.expired")}</p>
          ) : !complete ? (
            <p className="mt-2 text-xs text-muted">{t("feedback.incomplete")}</p>
          ) : null}
        </div>
      </Section>
    </div>
  );
}

const CALLS: Call[] = ["match", "mismatch", "pending"];

function RecordCard({
  index,
  total,
  record: r,
  call,
  note,
  onCall,
  onNote,
}: {
  index: number;
  total: number;
  record: RedactedRecord;
  call?: Call;
  note: string;
  onCall: (c: Call) => void;
  onNote: (n: string) => void;
}) {
  const t = useTranslations("task.record");
  return (
    <section className="panel" aria-label={t("label", { index, id: r.id })}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
        <h2 className="h-section">{t("heading", { index, total })}</h2>
        <Pill tone="human">{r.flag}</Pill>
      </div>
      <div className="grid gap-px bg-rule sm:grid-cols-2">
        <div className="bg-paper px-5 py-3.5">
          <div className="label mb-1">{t("order")}</div>
          <KeyValues
            rows={[
              { label: t("order"), value: <Id>{r.order.ref}</Id> },
              { label: t("placed"), value: r.order.date },
              { label: t("customer"), value: <span className="redact">{r.order.customer}</span> },
              { label: t("amount"), value: <span className="tnum font-medium">{r.order.amount}</span> },
              { label: t("paymentRef"), value: <Id>{r.order.paymentRef}</Id> },
            ]}
          />
        </div>
        <div className="bg-paper px-5 py-3.5">
          <div className="label mb-1">{t("payout")}</div>
          <KeyValues
            rows={[
              { label: t("reference"), value: <Id>{r.payment.ref}</Id> },
              { label: t("paidOut"), value: r.payment.date },
              { label: t("source"), value: <span className="redact">{r.payment.payer}</span> },
              { label: t("amount"), value: <span className="tnum font-medium">{r.payment.amount}</span> },
              { label: t("batch"), value: r.payment.batch },
            ]}
          />
        </div>
      </div>
      <div className="border-t border-rule px-5 py-3.5">
        <p className="text-sm">
          <span className="text-muted">{t("noticed")}</span> {r.agentNote}
        </p>
        <div className="mt-3">
          <Choices
            label={t("yourCall", { id: r.id })}
            layout="row"
            value={call ?? null}
            onValueChange={onCall}
            options={CALLS.map((c) => ({
              value: c,
              label: t(`calls.${c}`),
              tone: c === "mismatch" ? "blocked" : c === "pending" ? "human" : "default",
            }))}
          />
        </div>
        <input
          name={`note-${r.id}`}
          value={note}
          onChange={(e) => onNote(e.target.value)}
          placeholder={t("notePlaceholder")}
          aria-label={t("noteLabel", { id: r.id })}
          className="mt-3 h-9 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
        />
      </div>
    </section>
  );
}
