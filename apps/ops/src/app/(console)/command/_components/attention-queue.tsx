import { AlertTriangle, ChevronRight, Info, OctagonAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { OpsAttentionItem } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { ago } from "@/lib/format";
import { sortAttention } from "./logic";

const SEVERITY: Record<OpsAttentionItem["severity"], { icon: LucideIcon; text: string; label: string }> = {
  critical: { icon: OctagonAlert, text: "text-blocked", label: "Critical" },
  warn: { icon: AlertTriangle, text: "text-human", label: "Warning" },
  info: { icon: Info, text: "text-muted", label: "Info" },
};

/** Only same-site paths are linked; anything else (absolute or protocol-relative) falls back to the command center. */
const safeHref = (href: string) => (href.startsWith("/") && !href.startsWith("//") ? href : "/command");

/** What needs an operator now, most severe first. Every row deep-links to where the work is done. */
export function AttentionQueue({ items }: { items: OpsAttentionItem[] }) {
  const sorted = sortAttention(items);
  if (sorted.length === 0) {
    return <p className="px-5 py-10 text-center text-sm text-muted">Nothing needs attention. New items appear here.</p>;
  }
  return (
    <ul className="divide-y divide-rule">
      {sorted.map((item) => {
        const s = SEVERITY[item.severity];
        const Icon = s.icon;
        return (
          <li key={`${item.kind}-${item.href}-${item.at}`}>
            <Link
              href={safeHref(item.href)}
              className="group flex items-start gap-3 px-5 py-3 transition-colors hover:bg-grey-100/60 focus-visible:-outline-offset-2"
            >
              <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", s.text)} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">
                  <span className="sr-only">{s.label}: </span>
                  {item.title}
                </span>
                <span className="mt-0.5 block text-[13px] leading-snug text-muted">{item.detail}</span>
              </span>
              <span className="label tnum mt-0.5 shrink-0 whitespace-nowrap">{ago(item.at)}</span>
              <ChevronRight aria-hidden className="mt-0.5 size-4 shrink-0 text-grey-300 group-hover:text-ink" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
