import Link from "next/link";
import type { ComponentProps, ReactNode, Ref } from "react";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import type { Money, RunStatus } from "@/lib/types";

/* ── Status pills ── */

export type Tone = "machine" | "human" | "blocked" | "ink" | "quiet" | "policy";
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

const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  RUNNING: "Running",
  WAITING_FOR_HUMAN: "Waiting for a reviewer",
  WAITING_FOR_EVENT: "Waiting for approval",
  VERIFYING: "Verifying",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  NEEDS_ATTENTION: "Needs attention",
};

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

export function RunStatusPill({ status }: { status: RunStatus }) {
  return (
    <Pill tone={RUN_STATUS_TONE[status]} live={status === "RUNNING"}>
      {RUN_STATUS_LABEL[status]}
    </Pill>
  );
}

/* ── Money and simulation labels ── */

export function Amount({ value, className, sign }: { value: Money | number; className?: string; sign?: boolean }) {
  return <span className={cn("tnum", className)}>{money(value, { sign })}</span>;
}

/** Marks simulated figures (billing, health metrics, toolkit discovery, health checks). */
export function SimTag({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-dashed border-sim/50 bg-sim-soft px-1.5 py-px text-[11px] font-medium text-sim",
        className,
      )}
    >
      {children ?? "Simulated"}
    </span>
  );
}

export function MockTag({ className, children }: { className?: string; children?: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-dashed border-grey-300 px-1.5 py-px text-[11px] font-medium text-grey-700",
        className,
      )}
    >
      {children ?? "Sandbox mock"}
    </span>
  );
}

export function Id({ children, className }: { children: ReactNode; className?: string }) {
  return <code className={cn("font-mono text-[12px] text-grey-700", className)}>{children}</code>;
}

/* ── Layout helpers ── */

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
        <h1 tabIndex={-1} className="h-page outline-none">
          {title}
        </h1>
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
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Makes the heading a focus target, for when the control a person used disappears. */
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  return (
    <section className={cn("panel", className)}>
      {title ? (
        <div className="flex items-center justify-between gap-3 border-b border-rule px-5 py-3.5">
          <h2 ref={headingRef} tabIndex={headingRef ? -1 : undefined} className="h-section outline-none">
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
  /** Filled red, for the confirm button of a destructive action. */
  destructive: "bg-blocked text-paper hover:bg-[#991b1b]",
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
