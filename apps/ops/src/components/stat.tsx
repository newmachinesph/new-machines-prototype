import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { SimTag } from "./ui";

const VALUE_TONE = {
  default: "text-ink",
  machine: "text-machine",
  human: "text-human",
  blocked: "text-blocked",
} as const;

export type StatProps = {
  /** What is counted, in sentence case: "Active tenants". */
  label: ReactNode;
  /** The figure, already formatted (use `money`, `count` or `pct` from `@/lib/format`). */
  value: ReactNode;
  /** One line of context under the value: "2 on trial", "of $500.00 daily cap". */
  sub?: ReactNode;
  /** Adds a Simulated tag next to the label. Required for billing and health figures. */
  simulated?: boolean;
  /** Colours the value when it needs attention: human = waiting on people, blocked = failing or over a limit. */
  tone?: keyof typeof VALUE_TONE;
  /** Makes the whole tile a link to the page behind the figure. */
  href?: string;
  className?: string;
};

/** A KPI tile: label, value, optional sub line and Simulated tag. Lay several out in a responsive grid. */
export function Stat({ label, value, sub, simulated, tone = "default", href, className }: StatProps) {
  const body = (
    <>
      <div className="flex min-h-5 items-center justify-between gap-2">
        <span className="text-[13px] leading-tight text-muted">{label}</span>
        {simulated ? <SimTag /> : null}
      </div>
      <div className={cn("tnum mt-1.5 text-2xl leading-tight font-semibold tracking-tight", VALUE_TONE[tone])}>
        {value}
      </div>
      {sub ? <div className="mt-1 text-xs leading-snug text-muted">{sub}</div> : null}
    </>
  );
  const cls = cn("panel block min-w-0 px-4 py-3.5", className);
  return href ? (
    <Link href={href} className={cn(cls, "transition-colors hover:border-grey-300")}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}
