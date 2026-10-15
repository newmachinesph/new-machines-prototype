import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Actor } from "@/lib/types";
import { ActorGlyph } from "./ui";

/** The bar on the card's left edge, coloured by who does the step. */
const ACCENT: Record<Actor, string> = {
  machine: "before:bg-machine",
  human: "before:bg-human",
  policy: "before:bg-blocked",
  system: "before:bg-grey-300",
  buyer: "before:bg-ink",
};

const BORDER = {
  plain: "border-rule",
  selected: "border-ink ring-2 ring-ink/10",
  waiting: "border-human/60",
  blocked: "border-blocked/50",
} as const;
export type StepCardState = keyof typeof BORDER;

/**
 * One workflow step as a card: who does it, what kind of step it is, its name. Shared by the run canvas and the
 * workflow editor so a pack looks the same while it is built and while it runs. React Flow handles go beside the
 * card, not inside it: the node's wrapper positions them, and the card clips its own overflow.
 */
export function StepCard({
  actor,
  kind,
  title,
  subtitle,
  small,
  state = "plain",
  dim,
  aside,
  children,
  className,
  style,
}: {
  actor: Actor;
  kind: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  small?: boolean;
  state?: StepCardState;
  dim?: boolean;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      style={style}
      className={cn(
        "relative overflow-hidden rounded-[10px] border bg-paper py-2.5 pr-3 pl-3.5 text-left shadow-[0_1px_2px_rgb(17_17_17/0.05)] transition-shadow",
        "before:absolute before:inset-y-0 before:left-0 before:w-[3px]",
        ACCENT[actor],
        small ? "w-[150px]" : "w-[210px]",
        BORDER[state],
        dim && "opacity-70",
        className,
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] text-muted">
        <ActorGlyph actor={actor} className="size-2.5" />
        {kind}
        {aside ? <span className="tnum ml-auto">{aside}</span> : null}
      </div>
      <div className="mt-1 text-[13px] leading-snug font-semibold text-ink">{title}</div>
      {subtitle && !small ? <div className="mt-0.5 truncate text-[11.5px] text-muted">{subtitle}</div> : null}
      {children}
    </div>
  );
}
