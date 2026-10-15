"use client";

import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useId, useState } from "react";
import { cn } from "@/lib/cn";
import { Id } from "./ui";

/**
 * The ids, refs and hashes behind a record, folded away under "Technical details". They stay in the page for
 * anyone who needs to quote one; the main view reads in words. A string value is shown as an id.
 */
export function TechnicalDetails({
  rows,
  className,
}: {
  rows: { label: ReactNode; value: ReactNode }[];
  className?: string;
}) {
  const t = useTranslations("run.technical");
  return (
    <details className={cn("group rounded-[10px] border border-rule", className)}>
      <summary className="flex min-h-10 cursor-pointer list-none items-center gap-1.5 px-3.5 text-xs font-medium text-grey-700 hover:bg-grey-50/60 [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
        {t("title")}
      </summary>
      <dl className="divide-y divide-rule border-t border-rule px-3.5">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[minmax(6rem,36%)_1fr] gap-3 py-2 text-xs">
            <dt className="text-muted">{r.label}</dt>
            <dd className="min-w-0 break-all">
              {typeof r.value === "string" ? <Id className="text-[11px]">{r.value}</Id> : r.value}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/**
 * A panel that folds up on a phone (a toggle in its heading, closed to start) and is always open from `md` up,
 * where there is room for it. Layout decides, not state, so the server and the browser render the same page.
 */
export function CollapsibleSection({
  id,
  title,
  aside,
  children,
  className,
}: {
  id?: string;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const t = useTranslations("run.technical");
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  // A jump link to this panel (or a page loaded on its hash) lands on a closed body on a phone: open it, then look at it.
  useEffect(() => {
    if (!id) return;
    const show = () => {
      setOpen(true);
      requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView?.({ block: "start", behavior: "auto" }));
    };
    const onHash = () => {
      if (window.location.hash === `#${id}`) show();
    };
    const onClick = (e: MouseEvent) => {
      const link = e.target instanceof Element ? e.target.closest("a") : null;
      if (link?.getAttribute("href") === `#${id}`) show();
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    document.addEventListener("click", onClick);
    return () => {
      window.removeEventListener("hashchange", onHash);
      document.removeEventListener("click", onClick);
    };
  }, [id]);
  return (
    <section id={id} className={cn("panel", className)} aria-label={title}>
      <div className="flex items-center justify-between gap-3 border-b border-rule px-5 py-2.5 md:py-3.5">
        <h2 className="h-section">{title}</h2>
        <div className="flex items-center gap-2">
          {aside}
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((o) => !o)}
            className="-mr-2 grid size-10 place-items-center rounded-md text-grey-700 hover:bg-grey-100 md:hidden"
          >
            <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
            <span className="sr-only">{open ? t("collapse", { title }) : t("expand", { title })}</span>
          </button>
        </div>
      </div>
      <div id={bodyId} className={cn("md:block", !open && "hidden")}>
        {children}
      </div>
    </section>
  );
}
