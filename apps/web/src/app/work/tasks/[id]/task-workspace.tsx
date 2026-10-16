"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Choices, focusAfterClose, useToast } from "@/components/base";
import { Amount, Button, ButtonLink, Callout, Id, KeyValues, Pill, Section, SimTag } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useErrorText } from "@/lib/api/use-error-text";
import { WORKER_TZ } from "@/lib/format";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { useNow } from "@/lib/clock";
import { useFormat } from "@/lib/use-format";
import { useWorkerDateTime } from "../../worker-time";
import { useIsDemo } from "@/lib/queries/me";
import { useClaimTask, useSubmitReview } from "@/lib/queries/tasks";
import type { HumanTask, RedactedRecord, ReviewVerdict } from "@/lib/types";

type Phase = "offer" | "claimed" | "expired" | "validating" | "submitted" | "accepted" | "closed";
type Call = "match" | "mismatch" | "pending";
type Review = {
  verdict: ReviewVerdict;
  feedbackText: string;
  recordCalls: Record<string, Call>;
  recordNotes: Record<string, string>;
};
/** A review submitted in this session, and when. The API's task carries no copy of it. */
type Sent = { review: Review; at: string };

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
  const now = useNow();
  const demo = useIsDemo();
  const errorText = useErrorText();
  const toast = useToast();
  const claimTask = useClaimTask();
  const submitReview = useSubmitReview();
  const [phase, setPhase] = useState<Phase>(() => openingPhase(task));
  // A real run's task has no acceptance check: the verdict goes straight to the run, which goes on or stops.
  const realRun = Boolean(task.realRun);
  const [runOutcome, setRunOutcome] = useState<RunOutcome | undefined>(task.runOutcome ?? undefined);
  const [sent, setSent] = useState<Sent | null>(null);
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
  // A demo fixture without records is for looking only; a real run's task is always reviewable, with or
  // without records to call (a pack's review step may show none: then the verdict and feedback are the review).
  const interactive = realRun || task.records.length > 0;
  const holding = phase === "claimed" || phase === "expired";
  // A live task comes through the reviewer's own team (unpaid) or the network (simulated pay, another org's
  // run: its id is not the reviewer's to know, so the API sends it empty). A demo task has no `via`.
  const team = task.via === "team";
  const network = task.via === "network";
  const payNote = team ? t("payNote.team") : network ? t("payNote.network", { pay: money(task.pay) }) : null;
  const showRun = !network && Boolean(task.runId);
  const acceptedView = phase === "accepted" || (phase === "submitted" && task.state === "ACCEPTED");

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
          setSent({ review, at: now });
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
            {team ? (
              <span className="text-sm text-muted">{t("teamUnpaid")}</span>
            ) : (
              <>
                <Amount value={task.pay} className="block text-2xl font-semibold tracking-tight" />
                <span className="text-xs text-muted">
                  {/* The API's pay terms describe the demo's fixtures; a live task's pay is only simulated. */}
                  {demo ? t("simulatedPay", { terms: task.payTerms }) : t("simulatedPayLive")}
                </span>
              </>
            )}
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
      {phase === "submitted" && realRun ? (
        <RunSubmitted outcome={runOutcome} payNote={payNote} runHref={showRun ? `/app/runs/${task.runId}` : null} />
      ) : null}
      {phase === "submitted" && !realRun && task.state !== "ACCEPTED" ? (
        <Callout tone="info" title={t("submitted.title")}>
          {t("submitted.body")}{" "}
          <Link className="link" href="/work">
            {tWork("backToTasks")}
          </Link>
        </Callout>
      ) : null}
      {acceptedView ? (
        <div className="space-y-4">
          <Callout
            tone="info"
            title={
              team
                ? t("accepted.titleTeam")
                : network
                  ? t("accepted.titleNetwork", { pay: money(task.pay) })
                  : t("accepted.title", { pay: money(task.pay) })
            }
            action={
              team ? (
                <ButtonLink href="/work" variant="secondary">
                  {tWork("backToTasks")}
                </ButtonLink>
              ) : (
                <ButtonLink href="/work/earnings" variant="secondary">
                  {tWork("seeEarnings")}
                </ButtonLink>
              )
            }
          >
            {team || network ? t("accepted.bodyRun") : t("accepted.body")}
          </Callout>
          {showRun ? (
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
          ) : null}
        </div>
      ) : null}
      {phase === "submitted" || phase === "accepted" ? (
        // The accepted banner already offers Earnings (unless it is a team task, which it sends back to tasks).
        <ReviewSummary task={task} sent={sent} linkEarnings={!acceptedView || team} />
      ) : null}
    </div>
  );
}

/**
 * Read-only record of a finished review: the review itself when it was submitted in this session, otherwise
 * what the task asked for and where the verdict and time are listed (Earnings), since the API's task has
 * no copy of the review.
 */
function ReviewSummary({ task, sent, linkEarnings }: { task: HumanTask; sent: Sent | null; linkEarnings: boolean }) {
  const t = useTranslations("task.summary");
  const tTask = useTranslations("task");
  const tWork = useTranslations("work");
  const dateTime = useWorkerDateTime();
  const rows = [{ label: t("task"), value: task.question }];
  if (sent) {
    const { review } = sent;
    rows.push({ label: t("verdict"), value: tTask(`verdict.${review.verdict}.label`) });
    const itemNotes = task.records.flatMap((r) => {
      const note = review.recordNotes[r.id];
      return note ? [`${r.order.ref || r.id}: ${note}`] : [];
    });
    rows.push({ label: t("feedback"), value: [review.feedbackText, ...itemNotes].join("\n\n") });
    if (task.records.length > 0)
      rows.push({
        label: t("records"),
        value: task.records
          .flatMap((r) => {
            const call = review.recordCalls[r.id];
            return call ? [t("recordCall", { id: r.order.ref, call: tTask(`record.calls.${call}`) })] : [];
          })
          .join("\n"),
      });
    rows.push({ label: t("submitted"), value: dateTime(sent.at) });
  }
  const shown = rows.filter((r) => r.value.trim());
  return (
    <Section
      title={t("title")}
      aside={
        linkEarnings ? (
          <Link className="link text-sm" href="/work/earnings">
            {tWork("seeEarnings")}
          </Link>
        ) : null
      }
    >
      <div className="px-5 py-2">
        <KeyValues
          rows={shown.map((r) => ({ label: r.label, value: <span className="whitespace-pre-wrap">{r.value}</span> }))}
        />
      </div>
      {sent ? null : <p className="border-t border-rule px-5 py-3 text-sm text-muted">{t("onEarnings")}</p>}
    </Section>
  );
}

/**
 * A submitted review on a real run: what the run does with it, and what the review pays (team: unpaid, network:
 * simulated). Unknown outcome (an older answer): just recorded. This is also what a reload shows, so it keeps
 * the way back to the run (a team task's; a network task's run is not the reviewer's to open).
 */
function RunSubmitted({
  outcome,
  payNote,
  runHref,
}: {
  outcome?: RunOutcome;
  payNote: string | null;
  runHref: string | null;
}) {
  const t = useTranslations("task.runSubmitted");
  const tWork = useTranslations("work");
  const key = outcome === "STOPS" ? "stops" : outcome === "CONTINUES" ? "continues" : "recorded";
  return (
    <Callout tone={outcome === "STOPS" ? "warn" : "info"} title={t(`${key}Title`)}>
      {t(`${key}Body`)}{" "}
      {runHref ? (
        <>
          <Link className="link" href={runHref}>
            {t("openRun")}
          </Link>
          {" · "}
        </>
      ) : null}
      <Link className="link" href="/work">
        {tWork("backToTasks")}
      </Link>
      {payNote ? <span className="mt-1 block">{payNote}</span> : null}
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
  const tTask = useTranslations("task");
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
          {task.via === "team" ? (
            <>
              <div className="text-sm font-medium">{tTask("teamUnpaid")}</div>
              <p className="mt-1 text-xs text-muted">{t("teamNote")}</p>
            </>
          ) : (
            <>
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted">{t("willBePaid")}</span>
                <Amount value={task.pay} className="text-lg font-semibold" />
              </div>
              <p className="mt-1 text-xs text-muted">{task.via === "network" ? t("networkNote") : t("owedNote")}</p>
            </>
          )}
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
  // Only an order and its payment takes a call; any other item is reviewed through the verdict and notes.
  const toCall = task.records.filter((r) => !isItem(r));
  // With records to correct, a correction is the likely answer; with none, approving is.
  const [verdict, setVerdict] = useState<ReviewVerdict>(toCall.length > 0 ? "REVISION_REQUIRED" : "APPROVED");
  const [feedback, setFeedback] = useState("");
  const complete = toCall.every((r) => calls[r.id]) && feedback.trim().length >= 10;

  const send = () => {
    const recordCalls: Record<string, Call> = {};
    for (const r of toCall) {
      const call = calls[r.id];
      if (call) recordCalls[r.id] = call;
    }
    // The general note comes first, then each record's correction. An item's note travels by the id it was
    // shown, which the API maps back to the item's own (a network copy may rename it).
    const noteOf = (r: RedactedRecord) => (notes[r.id] ?? "").trim();
    const recordNotes: Record<string, string> = {};
    for (const r of task.records) if (isItem(r) && noteOf(r)) recordNotes[r.id] = noteOf(r);
    const corrections = task.records.filter((r) => !isItem(r)).map(noteOf);
    const feedbackText = [feedback.trim(), ...corrections].filter(Boolean).join("\n\n");
    onSubmit({ verdict, feedbackText, recordCalls, recordNotes });
  };

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <p className="max-w-[78ch] text-sm leading-relaxed text-grey-700">{task.instructions}</p>
        {task.details?.length ? (
          <Section title={t("details.title")}>
            <div className="px-5 py-2">
              <KeyValues
                rows={task.details.map((d) => ({
                  label: d.label,
                  value: <span className="whitespace-pre-wrap">{d.value}</span>,
                }))}
              />
            </div>
          </Section>
        ) : null}
        {task.records.map((r, i) =>
          isItem(r) ? (
            <ItemCard
              key={r.id}
              index={i + 1}
              total={task.records.length}
              record={r}
              note={notes[r.id] ?? ""}
              onNote={(n) => setNotes({ ...notes, [r.id]: n })}
            />
          ) : (
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
          ),
        )}
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
            <p className="mt-2 text-xs text-muted">
              {t(toCall.length > 0 ? "feedback.incomplete" : "feedback.incompleteNoRecords")}
            </p>
          ) : null}
        </div>
      </Section>
    </div>
  );
}

const CALLS: Call[] = ["match", "mismatch", "pending"];

/**
 * A shared review item (an invoice, a refund request, a support email...) rather than an order and its payment.
 * A record without a kind is a demo fixture, which is always a reconciliation.
 */
const isItem = (r: RedactedRecord) => r.kind === "item";

const NOTE_CLASS = "mt-3 h-9 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink";

/**
 * One review item as a plain card: what it is flagged for, its reference and date, its amount and related
 * reference when it has them, the agent's note, and an optional note for the item. No payment sides, and no
 * call to make: the verdict covers the items.
 */
function ItemCard({
  index,
  total,
  record: r,
  note,
  onNote,
}: {
  index: number;
  total: number;
  record: RedactedRecord;
  note: string;
  onNote: (n: string) => void;
}) {
  const t = useTranslations("task.item");
  const rows = [
    { label: t("reference"), value: <Id>{r.order.ref}</Id> },
    ...(r.order.date ? [{ label: t("date"), value: r.order.date }] : []),
    ...(r.order.amount
      ? [{ label: t("amount"), value: <span className="tnum font-medium">{r.order.amount}</span> }]
      : []),
    ...(r.order.paymentRef ? [{ label: t("related"), value: <Id>{r.order.paymentRef}</Id> }] : []),
  ];
  return (
    <section className="panel" aria-label={t("label", { index, id: r.id })}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
        <h2 className="h-section">{t("heading", { index, total })}</h2>
        <Pill tone="human">{r.flag}</Pill>
      </div>
      <div className="px-5 py-3.5">
        <KeyValues rows={rows} />
      </div>
      <div className="border-t border-rule px-5 py-3.5">
        {r.agentNote ? (
          <p className="text-sm">
            <span className="text-muted">{t("noted")}</span> {r.agentNote}
          </p>
        ) : null}
        <input
          name={`note-${r.id}`}
          value={note}
          onChange={(e) => onNote(e.target.value)}
          placeholder={t("notePlaceholder")}
          aria-label={t("noteLabel", { id: r.id })}
          className={NOTE_CLASS}
        />
      </div>
    </section>
  );
}

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
          className={NOTE_CLASS}
        />
      </div>
    </section>
  );
}
