import { getLocale, getTranslations } from "next-intl/server";
import type { CSSProperties, ReactNode } from "react";
import { ActorGlyph, ActorLabel, Pill, SimTag } from "@/components/ui";
import { RUN_1042 } from "@/data/runs-recon";
import { cn } from "@/lib/cn";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { money, sumMoney, time } from "@/lib/format";
import type { Actor } from "@/lib/types";
import { StageReveal } from "./stage-reveal";

type Line = { at: string; actor: Actor; who: string; text: ReactNode; quote?: boolean };
type StageId = "executed" | "verified" | "accepted" | "settled";
type AfterKey = "afterVerified" | "afterAccepted";
type Stage = { id: StageId; lines: Line[]; after?: AfterKey; simulated?: boolean };

const run = RUN_1042;
const reviewerNote = run.timeline.find((e) => e.actor === "human" && e.tone === "warn")?.detail ?? "";
const total = sumMoney(run.spent.ai, run.spent.human, run.spent.tools);

// Run 1042, told by the four outcome stages. Each line is an event from the run's own timeline, so the lines
// (who and text) stay English; only the headings and captions around them are translated.
const STAGES: Stage[] = [
  {
    id: "executed",
    lines: [
      {
        at: "2026-10-11T14:02:10Z",
        actor: "buyer",
        who: "You",
        text: "Started the run on orders for Oct 1–10, with a $50.00 budget.",
      },
      {
        at: "2026-10-11T14:02:31Z",
        actor: "machine",
        who: "Google Sheets",
        text: "Read 31 orders and 29 payout lines. Nothing was written.",
      },
      {
        at: "2026-10-11T14:03:48Z",
        actor: "machine",
        who: "Finance Agent",
        text: "Matched 28 orders. Flagged 3 that did not add up.",
      },
      {
        at: "2026-10-11T14:04:09Z",
        actor: "policy",
        who: "Policy",
        text: "Payment mismatches need a person. The run paused and saved its place.",
      },
      {
        at: "2026-10-11T14:38:02Z",
        actor: "human",
        who: "Reviewer 204",
        text: reviewerNote.replace(/^“|”$/g, ""),
        quote: true,
      },
      {
        at: "2026-10-11T14:38:40Z",
        actor: "machine",
        who: "Finance Agent",
        text: "Applied the corrections. 30 orders matched, 1 payout pending.",
      },
    ],
  },
  {
    id: "verified",
    lines: [
      {
        at: "2026-10-11T14:39:20Z",
        actor: "machine",
        who: "Independent check",
        text: "9 of 9 criteria passed. Totals tie out to the cent.",
      },
    ],
    after: "afterVerified",
  },
  {
    id: "accepted",
    lines: [
      { at: "2026-10-11T16:12:30Z", actor: "buyer", who: "You", text: "Read the two-page report and accepted it." },
    ],
    after: "afterAccepted",
  },
  {
    id: "settled",
    simulated: true,
    lines: [
      {
        at: "2026-10-11T16:12:31Z",
        actor: "system",
        who: "Ledger",
        text: `${money(total)} charged. ${money(run.spent.human)} paid to the reviewer.`,
      },
    ],
  },
];

// The one motion moment: each stage's rail fills, then its lines arrive. On wide screens all four
// stages enter view together, so the stage offsets play them left to right.
const STAGE_OFFSET = [0, 0.9, 1.4, 1.9];
const LINE_START = 0.2;
const LINE_STEP = 0.11;
const delay = (s: number) => ({ "--d": `${s}s` }) as CSSProperties;

const KEY: Actor[] = ["machine", "human", "policy", "buyer", "system"];

export async function RunRecord() {
  const t = await getTranslations("landing");
  const rec = await getTranslations("landing.record");
  const intl = INTL_TAGS[resolveLocale(await getLocale())];
  return (
    <section id="record" aria-labelledby="record-title" className="scroll-mt-4 border-y border-rule bg-stage">
      <div className="mx-auto max-w-[1600px] px-5 py-12 sm:px-10 lg:px-16 lg:py-16">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            {/* Harbor & Pine is a sample workspace, not the visitor's own: the record says so, and links nowhere
                a new workspace cannot follow. */}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <h2 id="record-title" className="text-[clamp(1.375rem,2.2vw,1.875rem)] font-semibold tracking-[-0.02em]">
                {rec("title")}
              </h2>
              <Pill tone="quiet">{rec("example")}</Pill>
            </div>
            <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-grey-700">
              {rec("intro", { title: run.title, total: money(total, {}, intl) })}
            </p>
          </div>
          <ul className="flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-grey-700" aria-label={rec("whoDidWhat")}>
            {KEY.map((a) => (
              <li key={a} className="flex items-center gap-2">
                <ActorGlyph actor={a} />
                <ActorLabel actor={a} />
              </li>
            ))}
          </ul>
        </div>

        <ol className="mt-10 grid grid-cols-1 gap-x-6 gap-y-12 lg:mt-12 lg:grid-cols-[minmax(0,2.3fr)_repeat(3,minmax(0,1fr))] lg:gap-y-0">
          {STAGES.map((stage, i) => (
            <StageReveal key={stage.id} offset={STAGE_OFFSET[i] ?? 0} className="min-w-0">
              <div className="flex items-baseline gap-3">
                <h3 className="font-display text-[clamp(1rem,1.35vw,1.375rem)] tracking-[0.02em]">
                  {t(`strip.${stage.id}`)}
                </h3>
                {stage.simulated ? <SimTag /> : null}
              </div>
              <div className="relative mt-4 h-[3px] bg-grey-200" aria-hidden>
                <span className="rail-fill absolute inset-0 bg-ink" style={delay(0)} />
                <span className="absolute top-1/2 left-0 size-2.5 -translate-y-1/2 rounded-full border-2 border-ink bg-paper" />
              </div>
              <ul className={cn("mt-6 space-y-5", i === 0 && "lg:max-w-[46rem]")}>
                {stage.lines
                  .filter((l) => l.text)
                  .map((l, j) => (
                    <li
                      key={l.at}
                      className="rail-arrive grid grid-cols-[4.75rem_minmax(0,1fr)] gap-x-3"
                      style={delay(LINE_START + j * LINE_STEP)}
                    >
                      <time dateTime={l.at} className="tnum pt-px text-[13px] text-grey-500">
                        {time(l.at, undefined, intl)}
                      </time>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-[13px] font-medium">
                          <ActorGlyph actor={l.actor} />
                          {l.who}
                        </div>
                        {l.quote ? (
                          <blockquote className="mt-2 border-l-[3px] border-human bg-human-soft/60 py-2.5 pr-3 pl-4 text-[15px] leading-relaxed text-ink">
                            {l.text}
                          </blockquote>
                        ) : (
                          <p className="mt-1 text-[15px] leading-snug text-grey-900">{l.text}</p>
                        )}
                      </div>
                    </li>
                  ))}
              </ul>
              {stage.after ? (
                <p
                  className="rail-arrive mt-5 pl-[5.5rem] text-[13px] leading-snug text-muted"
                  style={delay(LINE_START + stage.lines.length * LINE_STEP)}
                >
                  {rec(stage.after)}
                </p>
              ) : null}
            </StageReveal>
          ))}
        </ol>
      </div>
    </section>
  );
}
