"use client";

import { Autocomplete } from "@base-ui/react/autocomplete";
import { Dialog } from "@base-ui/react/dialog";
import { CornerDownLeft, Inbox, ListChecks, Search, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { useCategoryName, usePackText } from "@/lib/content-text";
import { usePacks } from "@/lib/queries/catalog";
import { useRuns } from "@/lib/queries/runs";
import { useEligibleTasks } from "@/lib/queries/tasks";
import { useApprovals } from "@/lib/queries/workspace";
import { useUi } from "@/stores/ui";
import type {
  ListApprovalsResponse,
  ListWorkflowPacksResponse,
  ListWorkflowRunsResponse,
  ListEligibleHumanTasksResponse,
  RunSummary,
} from "@/lib/api/gen/types.gen";
import { useIsDemo } from "@/lib/queries/me";
import { useFormat } from "@/lib/use-format";
import { PackIcon } from "./pack-icon";
import { useTour } from "./tour/tour-context";

// Pages show their sidebar icon plain; records (runs, packs, approvals, tasks) sit in a ring.
type Entry = {
  id: string;
  label: string;
  /** What tells this row from its neighbours: a run's status and age, a pack's category, a task's id. */
  hint?: string;
  /** The hint is an id, set in monospace. */
  mono?: boolean;
  href: string;
  keywords: string;
  pack?: string;
  icon?: LucideIcon;
  ring?: boolean;
  /** An action rather than a page: run with what had focus before the palette opened. */
  run?: (opener: Element | null) => void;
};
// The id is the stable key; the label is translated at build time.
type Group = { id: string; label: string; items: Entry[] };
type PaletteKey = "approval" | "hired" | `groups.${"pages" | "actions" | "runs" | "needsYou" | "packs" | "tasks"}`;
type Translate = (key: PaletteKey) => string;

export type PageEntry = { href: string; label: string; icon: LucideIcon };
/** Something to do from the palette, such as replaying the page's tour. */
export type PaletteAction = { id: string; label: string; icon: LucideIcon; run: (opener: Element | null) => void };

type Records = {
  runs?: ListWorkflowRunsResponse;
  approvals?: ListApprovalsResponse;
  packs?: ListWorkflowPacksResponse;
  tasks?: ListEligibleHumanTasksResponse;
};
/** Our own packs and the taxonomy's names in the interface language (lib/content-text). */
type ContentText = { pack: ReturnType<typeof usePackText>; category: ReturnType<typeof useCategoryName> };

function buildGroups(
  pages: PageEntry[],
  actions: PaletteAction[],
  { runs = [], approvals = [], packs = [], tasks = [] }: Records,
  t: Translate,
  runHint: (run: RunSummary) => string,
  text: ContentText,
): Group[] {
  return [
    {
      // The group's name already says these are pages; each row needs no hint of its own.
      id: "pages",
      label: t("groups.pages"),
      items: pages.map((p) => ({
        id: p.href,
        label: p.label,
        href: p.href,
        keywords: p.href,
        icon: p.icon,
      })),
    },
    {
      id: "actions",
      label: t("groups.actions"),
      items: actions.map((a) => ({
        id: `action-${a.id}`,
        label: a.label,
        href: "",
        keywords: a.id,
        icon: a.icon,
        run: a.run,
      })),
    },
    {
      id: "runs",
      label: t("groups.runs"),
      items: runs
        .filter((r) => r.hasDetail)
        .map((r) => ({
          id: r.id,
          label: r.title,
          // Runs of one pack share a title; their status and age tell them apart. The id still matches a search.
          hint: runHint(r),
          href: `/app/runs/${r.id}`,
          keywords: `${r.id} ${packs.find((p) => p.slug === r.packSlug)?.name ?? ""} ${r.summary}`,
          pack: r.packSlug,
        })),
    },
    {
      id: "needsYou",
      label: t("groups.needsYou"),
      items: approvals
        .filter((a) => a.status === "PENDING")
        .map((a) => ({
          id: a.id,
          label: a.title,
          hint: t("approval"),
          href: "/app/approvals",
          keywords: `${a.id} approve approval`,
          icon: ListChecks,
          ring: true,
        })),
    },
    {
      id: "packs",
      label: t("groups.packs"),
      items: packs.map((pack) => {
        // The row reads in the interface language; a search still matches the API's English behind it.
        const p = text.pack(pack);
        return {
          id: p.slug,
          label: p.name,
          hint: p.installed ? t("hired") : text.category(p.category),
          href: `/app/marketplace/${p.slug}`,
          keywords: `${pack.name} ${pack.outcome} ${p.outcome} ${p.publisher} ${p.category} ${text.category(p.category)}`,
          pack: p.slug,
        };
      }),
    },
    {
      id: "tasks",
      label: t("groups.tasks"),
      items: tasks.map((task) => ({
        id: task.id,
        label: task.title,
        hint: task.id,
        mono: true,
        href: `/work/tasks/${task.id}`,
        keywords: `${task.id} ${task.packName} ${task.skill}`,
        icon: Inbox,
        ring: true,
      })),
    },
  ];
}

function EntryIcon({ entry }: { entry: Entry }) {
  if (entry.pack) return <PackIcon slug={entry.pack} className="size-6 [&_svg]:size-3" />;
  const Icon = entry.icon;
  if (!Icon) return <span className="size-6 shrink-0" aria-hidden />;
  return (
    <span
      className={cn(
        "grid size-6 shrink-0 place-items-center",
        entry.ring ? "rounded-full border border-rule bg-paper text-ink" : "text-grey-500",
      )}
      aria-hidden
    >
      <Icon className={entry.ring ? "size-3" : "size-4"} strokeWidth={1.75} />
    </span>
  );
}

const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function CommandPalette({ pages, actions = [] }: { pages: PageEntry[]; actions?: PaletteAction[] }) {
  const t = useTranslations("nav.palette");
  const status = useTranslations("status");
  const { ago } = useFormat();
  const packText = usePackText();
  const categoryName = useCategoryName();
  const demo = useIsDemo();
  const open = useUi((s) => s.paletteOpen);
  const onOpenChange = useUi((s) => s.setPaletteOpen);
  // A product tour on screen owns the keyboard: its card keeps focus, and Escape and the arrows drive it.
  const tourVisible = useTour().visible;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (tourVisible) return;
      const key = e.key?.toLowerCase();
      const k = key === "k" && (e.metaKey || e.ctrlKey);
      if (k || (key === "/" && !isTyping(e.target))) {
        e.preventDefault();
        onOpenChange(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onOpenChange, tourVisible]);

  // What had focus when the palette opened, however it was opened, for an action to hand focus back to.
  const returnTo = useRef<Element | null>(null);
  useEffect(
    () =>
      useUi.subscribe((s, prev) => {
        if (s.paletteOpen && !prev.paletteOpen) returnTo.current = document.activeElement;
      }),
    [],
  );

  // Palette data loads only while the palette is open.
  const runs = useRuns(open);
  const approvals = useApprovals(open);
  const packs = usePacks(open);
  const tasks = useEligibleTasks(open);
  const loading = open && [runs, approvals, packs, tasks].some((q) => q.isPending);
  const groups = buildGroups(
    pages,
    actions,
    { runs: runs.data, approvals: approvals.data, packs: packs.data, tasks: tasks.data },
    t,
    (r) => t("runHint", { status: status(r.status), when: ago(r.startedAt) }),
    { pack: packText, category: categoryName },
  );
  const close = () => onOpenChange(false);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => onOpenChange(o)}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-ink/25 transition-opacity duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup className="fixed top-[12vh] left-1/2 z-50 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-[12px] border border-rule bg-paper shadow-[0_16px_48px_rgb(17_17_17/0.18)] transition-[opacity,transform] duration-150 outline-none data-[ending-style]:opacity-0 data-[starting-style]:scale-[0.98] data-[starting-style]:opacity-0">
          <Dialog.Title className="sr-only">{t("title")}</Dialog.Title>
          <Autocomplete.Root
            items={groups}
            inline
            autoHighlight
            itemToStringValue={(e: Entry) => `${e.label} ${e.keywords}`}
          >
            <div className="flex items-center gap-3 border-b border-rule px-4">
              <Search className="size-4 shrink-0 text-grey-500" strokeWidth={1.75} aria-hidden />
              <Autocomplete.Input
                aria-label={t("placeholder")}
                placeholder={t("placeholder")}
                className="h-13 w-full bg-transparent text-[15px] outline-none placeholder:text-grey-500"
              />
              <kbd className="shrink-0 rounded border border-rule px-1.5 font-sans text-[11px] text-grey-500">Esc</kbd>
            </div>
            <Autocomplete.Empty className="px-4 py-8 text-center text-sm text-muted empty:hidden">
              {t("empty")}
            </Autocomplete.Empty>
            <Autocomplete.List className="max-h-[min(60vh,480px)] overflow-y-auto p-1.5 empty:hidden">
              {(group: Group) => (
                <Autocomplete.Group key={group.id} items={group.items} className="pb-1">
                  <Autocomplete.GroupLabel className="px-2.5 pt-2 pb-1 text-xs text-muted">
                    {group.label}
                  </Autocomplete.GroupLabel>
                  <Autocomplete.Collection>
                    {(e: Entry) => (
                      <Autocomplete.Item
                        key={e.id}
                        value={e}
                        render={
                          e.run ? (
                            <button
                              type="button"
                              onClick={() => {
                                const opener = returnTo.current;
                                close();
                                e.run?.(opener);
                              }}
                            />
                          ) : (
                            <Link href={e.href} onClick={close} />
                          )
                        }
                        className="group flex items-center gap-3 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-grey-100"
                      >
                        <EntryIcon entry={e} />
                        <span className="min-w-0 flex-1 truncate">{e.label}</span>
                        {e.hint ? (
                          <span className={cn("shrink-0 text-muted", e.mono ? "font-mono text-[11px]" : "text-xs")}>
                            {e.hint}
                          </span>
                        ) : null}
                        <CornerDownLeft
                          className="size-3.5 shrink-0 text-grey-500 opacity-0 group-data-[highlighted]:opacity-100"
                          aria-hidden
                        />
                      </Autocomplete.Item>
                    )}
                  </Autocomplete.Collection>
                </Autocomplete.Group>
              )}
            </Autocomplete.List>
            <div className="flex items-center gap-4 border-t border-rule bg-stage/60 px-4 py-2 text-xs text-muted">
              <span>
                <kbd className="font-sans">↑↓</kbd> {t("toMove")}
              </span>
              <span>
                <kbd className="font-sans">Enter</kbd> {t("toOpen")}
              </span>
              {/* The demo's search is bounded by its seed; a live workspace's search covers its own records. */}
              <span role="status" className="ml-auto">
                {loading ? t("loading") : demo ? t("demoOnly") : null}
              </span>
            </div>
          </Autocomplete.Root>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
