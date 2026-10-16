import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import type { ComponentProps, ReactNode, Ref } from "react";
import { cn } from "@/lib/cn";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { money } from "@/lib/format";
import type { Actor, Money, NodeStatus, OutcomeStage, RunStatus, StageState } from "@/lib/types";

/* ── Actor glyphs: who did the work. Shape carries meaning without colour. ── */

export const ACTOR_TEXT: Record<Actor, string> = {
  machine: "text-machine",
  human: "text-human",
  policy: "text-policy",
  system: "text-grey-500",
  buyer: "text-ink",
};

export function ActorGlyph({ actor, className }: { actor: Actor; className?: string }) {
  const c = cn("inline-block shrink-0", ACTOR_TEXT[actor], className ?? "size-3");
  switch (actor) {
    case "machine":
      return (
        <svg viewBox="0 0 12 12" aria-hidden className={c}>
          <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill="currentColor" />
        </svg>
      );
    case "human":
      return (
        <svg viewBox="0 0 12 12" aria-hidden className={c}>
          <circle cx="6" cy="6" r="4.75" fill="currentColor" />
        </svg>
      );
    case "policy":
      return (
        <svg viewBox="0 0 12 12" aria-hidden className={c}>
          <path d="M4 1h4l3 3v4l-3 3H4L1 8V4z" fill="currentColor" />
        </svg>
      );
    case "buyer":
      return (
        <svg viewBox="0 0 12 12" aria-hidden className={c}>
          <circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 12 12" aria-hidden className={c}>
          <path d="M6 1.5 10.5 6 6 10.5 1.5 6z" fill="currentColor" />
        </svg>
      );
  }
}

/** Who did the work, in words. Labels live under `common.actor`. */
export function ActorLabel({ actor }: { actor: Actor }) {
  const t = useTranslations("common.actor");
  return <>{t(actor)}</>;
}

/* ── Status pills ── */

type Tone = "machine" | "human" | "blocked" | "ink" | "quiet" | "policy";
const TONE: Record<Tone, string> = {
  machine: "bg-machine-soft text-machine",
  human: "bg-human-soft text-human",
  blocked: "bg-blocked-soft text-blocked",
  ink: "bg-ink text-paper",
  quiet: "bg-grey-100 text-grey-700",
  policy: "bg-policy-soft text-policy",
};

function ToneIcon({ tone, live }: { tone: Tone; live?: boolean }) {
  const p = {
    viewBox: "0 0 12 12",
    "aria-hidden": true,
    className: cn("size-3 shrink-0", live && "live-dot"),
  } as const;
  if (tone === "machine")
    return (
      <svg {...p}>
        <circle cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 2" />
      </svg>
    );
  if (tone === "human")
    return (
      <svg {...p}>
        <circle cx="6" cy="4" r="2.2" fill="currentColor" />
        <path d="M1.5 11a4.5 4.5 0 0 1 9 0Z" fill="currentColor" />
      </svg>
    );
  if (tone === "ink")
    return (
      <svg {...p}>
        <path d="M2 6.5 4.8 9.3 10 3.6" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  if (tone === "blocked")
    return (
      <svg {...p}>
        <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  if (tone === "policy")
    return (
      <svg {...p}>
        <path d="M4 1h4l3 3v4l-3 3H4L1 8V4z" fill="currentColor" />
      </svg>
    );
  return (
    <svg {...p}>
      <circle cx="6" cy="6" r="3" fill="currentColor" />
    </svg>
  );
}

export function Pill({
  tone = "quiet",
  live,
  children,
  className,
}: {
  tone?: Tone;
  live?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      <ToneIcon tone={tone} live={live} />
      {children}
    </span>
  );
}

// Labels come from `status.<STATUS>` and `node.<STATUS>`; only the tone is decided here.
const RUN_STATUS_TONE: Record<RunStatus, Tone> = {
  RUNNING: "machine",
  WAITING_FOR_HUMAN: "human",
  WAITING_FOR_EVENT: "human",
  VERIFYING: "machine",
  COMPLETED: "ink",
  FAILED: "blocked",
  CANCELLED: "quiet",
  NEEDS_ATTENTION: "blocked",
};

/** A run's status. A failed run that a person stopped by declining its approval reads "Declined", not "Failed". */
export function RunStatusPill({ status, stopReason }: { status: RunStatus; stopReason?: "declined" | null }) {
  const t = useTranslations("status");
  if (status === "FAILED" && stopReason === "declined") return <Pill tone="quiet">{t("DECLINED")}</Pill>;
  return (
    <Pill tone={RUN_STATUS_TONE[status]} live={status === "RUNNING"}>
      {t(status)}
    </Pill>
  );
}

const NODE_STATUS_TONE: Record<NodeStatus, Tone> = {
  CREATED: "quiet",
  READY: "quiet",
  RUNNING: "machine",
  WAITING: "human",
  VALIDATING: "machine",
  COMPLETED: "ink",
  FAILED: "blocked",
  REJECTED: "blocked",
  TIMED_OUT: "blocked",
  CANCELLED: "quiet",
  COMPENSATING: "machine",
  ESCALATED: "human",
  BLOCKED: "blocked",
  SKIPPED: "quiet",
};

export function NodeStatusPill({ status }: { status: NodeStatus }) {
  const t = useTranslations("node");
  return (
    <Pill tone={NODE_STATUS_TONE[status]} live={status === "RUNNING"}>
      {t(status)}
    </Pill>
  );
}

/* ── The four outcome stages. Never merged into one status. ── */

// Stage names come from `stage.<key>`, stage states from `stage.state.<state>`.
const STAGE_KEYS: OutcomeStage[] = ["executed", "verified", "accepted", "settlement"];

const STAGE_STATE: Record<StageState, { cls: string; icon: ReactNode }> = {
  done: {
    cls: "text-ink",
    icon: <path d="M2.5 6.5 5 9l4.5-5.5" fill="none" stroke="currentColor" strokeWidth="2" />,
  },
  pending: {
    cls: "text-grey-500",
    icon: <circle cx="6" cy="6" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />,
  },
  failed: {
    cls: "text-blocked",
    icon: <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="2" />,
  },
  blocked: {
    cls: "text-blocked",
    icon: <path d="M2.5 6h7" stroke="currentColor" strokeWidth="2.5" />,
  },
  not_required: {
    cls: "text-grey-500",
    icon: <path d="M3 6h6" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 1.5" />,
  },
};

export function OutcomeRail({
  stages,
  notes,
  compact,
}: {
  stages: Record<OutcomeStage, StageState>;
  notes?: Partial<Record<OutcomeStage, string>>;
  compact?: boolean;
}) {
  const t = useTranslations("stage");
  if (compact) {
    return (
      <span className="inline-flex items-center gap-2" aria-label={t("railLabel")}>
        {STAGE_KEYS.map((key) => {
          const st = STAGE_STATE[stages[key]];
          const text = t("withState", { stage: t(key), state: t(`state.${stages[key]}`) });
          return (
            <span key={key} title={text} className={cn("inline-flex", st.cls)}>
              <svg viewBox="0 0 12 12" className="size-3.5" aria-hidden>
                {st.icon}
              </svg>
              <span className="sr-only">{text}</span>
            </span>
          );
        })}
      </span>
    );
  }
  return (
    <ol className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-rule bg-rule sm:grid-cols-4">
      {STAGE_KEYS.map((key) => {
        const state = stages[key];
        const st = STAGE_STATE[state];
        return (
          <li key={key} className={cn("bg-paper px-3.5 py-3", state === "done" && "bg-paper")}>
            <div className="label">{t(key)}</div>
            <div className={cn("mt-1 flex items-center gap-1.5 text-sm font-medium", st.cls)}>
              <svg viewBox="0 0 12 12" className="size-3.5 shrink-0" aria-hidden>
                {st.icon}
              </svg>
              {t(`state.${state}`)}
            </div>
            {notes?.[key] ? <div className="mt-1 text-xs leading-snug text-muted">{notes[key]}</div> : null}
          </li>
        );
      })}
    </ol>
  );
}

/* ── Money and simulation labels ── */

export function Amount({ value, className, sign }: { value: Money | number; className?: string; sign?: boolean }) {
  const locale = INTL_TAGS[resolveLocale(useLocale())];
  return <span className={cn("tnum", className)}>{money(value, { sign }, locale)}</span>;
}

export function SimTag({ children, className }: { children?: ReactNode; className?: string }) {
  const t = useTranslations("common");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-dashed border-sim/50 bg-sim-soft px-1.5 py-px text-[11px] font-medium text-sim",
        className,
      )}
    >
      {children ?? t("simulated")}
    </span>
  );
}

export function MockTag({ className }: { className?: string }) {
  const t = useTranslations("common");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-dashed border-grey-300 px-1.5 py-px text-[11px] font-medium text-grey-700",
        className,
      )}
    >
      {t("sandboxMock")}
    </span>
  );
}

export function Id({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cn("font-mono text-[12px] text-grey-700", className)}>{children}</code>;
}

/* ── Layout helpers ── */

/** A list with nothing in it yet: what that means, and the next thing to do. Put it inside a panel. */
export function EmptyState({
  children,
  action,
  className,
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-3 px-5 py-8 text-center text-sm text-muted", className)}>
      <p className="max-w-[60ch] leading-relaxed">{children}</p>
      {action}
    </div>
  );
}

export function PageHeader({
  title,
  lede,
  actions,
  children,
}: {
  title: ReactNode;
  lede?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <div className="min-w-0">
        {children}
        <h1 className="h-page">{title}</h1>
        {lede ? <p className="mt-1.5 max-w-[68ch] text-[15px] leading-relaxed text-muted">{lede}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}

export function Section({
  title,
  aside,
  children,
  className,
  headingRef,
  "data-tour": tour,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Makes the heading a focus target, for when the control a person used disappears. */
  headingRef?: Ref<HTMLHeadingElement>;
  /** A product tour step's target. */
  "data-tour"?: string;
}) {
  return (
    <section className={cn("panel", className)} data-tour={tour}>
      {title ? (
        <div className="flex items-center justify-between gap-3 border-b border-rule px-5 py-3.5">
          <h2
            ref={headingRef}
            tabIndex={headingRef ? -1 : undefined}
            className="h-section scroll-mt-24 outline-none lg:scroll-mt-16"
          >
            {title}
          </h2>
          {aside}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function KeyValues({ rows, className }: { rows: { label: ReactNode; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("divide-y divide-rule", className)}>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[minmax(7rem,38%)_1fr] gap-4 py-2.5 text-sm">
          <dt className="text-muted">{r.label}</dt>
          <dd className="min-w-0 break-words">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ── Buttons ── */

const BTN = {
  primary: "bg-ink text-paper hover:bg-grey-900",
  secondary: "border border-grey-300 bg-paper text-ink hover:border-ink",
  ghost: "text-ink hover:bg-grey-100",
  danger: "border border-blocked/40 bg-paper text-blocked hover:border-blocked",
} as const;
const BTN_BASE =
  "inline-flex h-9 items-center justify-center gap-2 rounded-md px-3.5 text-sm font-medium whitespace-nowrap transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45";

export function Button({
  variant = "primary",
  className,
  ...rest
}: ComponentProps<"button"> & { variant?: keyof typeof BTN }) {
  return <button type="button" className={cn(BTN_BASE, BTN[variant], className)} {...rest} />;
}

export function ButtonLink({
  variant = "primary",
  className,
  ...rest
}: ComponentProps<typeof Link> & { variant?: keyof typeof BTN }) {
  return <Link className={cn(BTN_BASE, BTN[variant], className)} {...rest} />;
}

/* ── Callout used for "needs attention" banners ── */

const CALLOUT: Record<"human" | "blocked" | "warn" | "info", string> = {
  human: "border-human/30 bg-human-soft/60",
  blocked: "border-blocked/30 bg-blocked-soft/60",
  warn: "border-human/30 bg-human-soft/40",
  info: "border-machine/25 bg-machine-soft/50",
};

export function Callout({
  tone,
  title,
  children,
  action,
  announce = true,
}: {
  tone: keyof typeof CALLOUT;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** Off when the page announces the same news through its own live region. */
  announce?: boolean;
}) {
  const icon: Tone = tone === "info" ? "machine" : tone === "blocked" ? "blocked" : "human";
  return (
    <div
      role={announce ? (tone === "blocked" ? "alert" : "status") : undefined}
      className={cn(
        "flex flex-col gap-3 rounded-[10px] border px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between",
        CALLOUT[tone],
      )}
    >
      <div className="flex gap-3">
        <span
          className={cn(
            "mt-0.5",
            tone === "blocked" ? "text-blocked" : tone === "info" ? "text-machine" : "text-human",
          )}
        >
          <ToneIcon tone={icon} />
        </span>
        <div>
          <div className="text-sm font-semibold">{title}</div>
          {children ? (
            <div className="mt-0.5 max-w-[78ch] text-sm leading-relaxed text-grey-700">{children}</div>
          ) : null}
        </div>
      </div>
      {action ? <div className="shrink-0 pl-6 sm:pl-0">{action}</div> : null}
    </div>
  );
}
