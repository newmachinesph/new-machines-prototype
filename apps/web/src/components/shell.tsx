"use client";

import { Dialog } from "@base-ui/react/dialog";
import {
  ArrowLeftRight,
  Bot,
  Brain,
  Check,
  ChevronRight,
  Hammer,
  ChevronsUpDown,
  LogOut,
  CircleDollarSign,
  House,
  Inbox,
  LayoutGrid,
  ListChecks,
  Plug,
  Plus,
  Search,
  Settings,
  Store,
  UserCheck,
  Wallet,
  Workflow,
  X,
  Menu as MenuIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import { useEffect, useId, type ReactNode } from "react";
import { Mark } from "@/design-system/logo/Mark";
import { useSession } from "@/lib/auth/session";
import { ClockProvider } from "@/lib/clock";
import { cn } from "@/lib/cn";
import { useAgentName, usePackName, usePacks } from "@/lib/queries/catalog";
import { useIsDemo, useIsLive, useMe } from "@/lib/queries/me";
import { useOrg } from "@/lib/queries/org";
import { useStudioAgent, useStudioPack } from "@/lib/queries/studio";
import { useEligibleTasks } from "@/lib/queries/tasks";
import { useApprovals, useMemory } from "@/lib/queries/workspace";
import { useUi } from "@/stores/ui";
import {
  MenuGroup,
  MenuGroupLabel,
  MenuItem,
  MenuLabel,
  MenuLink,
  MenuPopup,
  MenuRoot,
  MenuSeparator,
  MenuTrigger,
  Tooltip,
  useToast,
} from "./base";
import { CommandPalette } from "./command-palette";
import { LanguageMenuItems } from "./language-switch";
import { PackIcon } from "./pack-icon";

type PageKey =
  | "overview"
  | "runs"
  | "approvals"
  | "marketplace"
  | "agents"
  | "memory"
  | "connections"
  | "usage"
  | "settings"
  | "reviewers"
  | "availableTasks"
  | "earnings"
  | "studio"
  | "studioAgents"
  | "studioPacks"
  | "developerStudio"
  | "reviewerPortal";
type CrumbKey = "crumbDeliverable" | "crumbHire" | "crumbStartRun" | "crumbNew" | "crumbTask";
type GroupKey = "work" | "setup" | "account" | "other";

/** `label` is a key under `nav`. */
type Item = { href: string; label: PageKey; icon: LucideIcon; exact?: boolean; liveOnly?: boolean };
/** A labelled run of sidebar links; `label` is a key under `nav.groups`. A single unlabelled group is a plain list. */
type Group = { label?: GroupKey; items: Item[] };

const BUSINESS_NAV: Group[] = [
  {
    label: "work",
    items: [
      { href: "/app", label: "overview", icon: House, exact: true },
      { href: "/app/runs", label: "runs", icon: Workflow },
      { href: "/app/approvals", label: "approvals", icon: ListChecks },
      { href: "/app/marketplace", label: "marketplace", icon: Store },
      { href: "/app/agents", label: "agents", icon: Bot },
    ],
  },
  {
    label: "setup",
    items: [
      { href: "/app/memory", label: "memory", icon: Brain },
      { href: "/app/connections", label: "connections", icon: Plug },
      { href: "/app/reviewers", label: "reviewers", icon: UserCheck, liveOnly: true },
    ],
  },
  {
    label: "account",
    items: [
      { href: "/app/usage", label: "usage", icon: CircleDollarSign },
      { href: "/app/settings", label: "settings", icon: Settings },
    ],
  },
  // Other roles' areas: the reviewer portal, and where a business builds its own agents and packs (live only).
  {
    label: "other",
    items: [
      { href: "/work", label: "reviewerPortal", icon: ArrowLeftRight },
      { href: "/studio", label: "developerStudio", icon: Hammer, liveOnly: true },
    ],
  },
];

const WORK_NAV: Group[] = [
  {
    items: [
      { href: "/work", label: "availableTasks", icon: Inbox, exact: true },
      { href: "/work/earnings", label: "earnings", icon: Wallet },
    ],
  },
];

const STUDIO_NAV: Group[] = [
  {
    items: [
      { href: "/studio", label: "studio", icon: House, exact: true },
      { href: "/studio/agents", label: "studioAgents", icon: Bot },
      { href: "/studio/packs", label: "studioPacks", icon: Workflow },
    ],
  },
];

/** Which view a layout shows: the business workspace, the reviewer portal or the Developer Studio. */
export type ShellMode = "business" | "work" | "studio";
const NAV: Record<ShellMode, Group[]> = { business: BUSINESS_NAV, work: WORK_NAV, studio: STUDIO_NAV };
const HOME: Record<ShellMode, string> = { business: "/app", work: "/work", studio: "/studio" };

/** The pages a view offers, in the sidebar and the command palette alike. Reviewer management and the
 * Developer Studio exist only in a live workspace, so the demo's navigation is unchanged. */
const navFor = (mode: ShellMode, live: boolean): Group[] =>
  NAV[mode].map((g) => ({ ...g, items: g.items.filter((item) => live || !item.liveOnly) }));

type Crumb = { label: string; href?: string; mono?: boolean };

// Path segments that name a sub-page rather than a record; values are keys under `nav`.
const SUBPAGE: Record<string, CrumbKey> = { evidence: "crumbDeliverable", install: "crumbHire", new: "crumbStartRun" };

function crumbsFor(
  path: string,
  mode: ShellMode,
  recordName: string | undefined,
  t: (key: PageKey | CrumbKey) => string,
): Crumb[] {
  const parts = path.split("/").filter(Boolean);
  const nav = NAV[mode].flatMap((g) => g.items);
  const out: Crumb[] = [];
  let href = `/${parts[0] ?? ""}`;
  parts.slice(1).forEach((seg, i) => {
    href += `/${seg}`;
    if (i === 0) {
      if (seg === "tasks") out.push({ label: t("availableTasks"), href: "/work" });
      else {
        const key = nav.find((n) => n.href === href)?.label;
        out.push({ label: key ? t(key) : seg, href });
      }
    } else if (mode === "studio" && seg === "new") {
      out.push({ label: t("crumbNew"), href });
    } else if (SUBPAGE[seg]) {
      out.push({ label: t(SUBPAGE[seg]), href });
    } else if (mode === "work") {
      // A reviewer task's id is no name; the page itself carries the title.
      out.push({ label: t("crumbTask"), href });
    } else {
      out.push(recordName ? { label: recordName, href } : { label: seg, href, mono: true });
    }
  });
  if (!out.length)
    out.push({ label: t(mode === "work" ? "availableTasks" : mode === "studio" ? "studio" : "overview") });
  return out;
}

function Breadcrumbs({ path, mode }: { path: string; mode: ShellMode }) {
  const slug = /^\/app\/marketplace\/([^/]+)/.exec(path)?.[1];
  const agentId = /^\/app\/agents\/([^/]+)/.exec(path)?.[1];
  const studio = /^\/studio\/(agents|packs)\/([^/]+)/.exec(path);
  const studioKey = studio?.[2] === "new" ? undefined : studio?.[2];
  const studioAgent = useStudioAgent(studio?.[1] === "agents" ? studioKey : undefined);
  const studioPack = useStudioPack(studio?.[1] === "packs" ? studioKey : undefined);
  // The record's name once it has loaded. Until then a Studio key, <org namespace>--<name>, reads as its name part.
  const studioName = studioAgent.data?.draft.name ?? studioPack.data?.draft.name ?? studioKey?.split("--").pop();
  const packName = usePackName(slug);
  const agentName = useAgentName(agentId);
  const t = useTranslations("nav");
  const crumbs = crumbsFor(path, mode, packName ?? agentName ?? studioName, t);
  // A single crumb only names the page. When the page carries its own heading, the shell hides it (see
  // AppShell), so the name shows once; a trail stays, since it is how a person gets back up. The reviewer
  // portal's pages keep theirs, so its top bar is never empty.
  return (
    <nav aria-label={t("breadcrumb")} className={cn("min-w-0", crumbs.length === 1 && mode !== "work" && "page-crumb")}>
      <ol className="flex min-w-0 items-center gap-1.5 text-sm">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={`${c.label}-${i}`} className={cn("flex min-w-0 items-center gap-1.5", !last && "hidden sm:flex")}>
              {i > 0 ? <ChevronRight className="size-3.5 shrink-0 text-grey-300" aria-hidden /> : null}
              {last || !c.href ? (
                <span
                  aria-current={last ? "page" : undefined}
                  className={cn("truncate font-medium", c.mono && "font-mono text-[13px]")}
                >
                  {c.label}
                </span>
              ) : (
                <Link
                  href={c.href}
                  className={cn("truncate text-grey-700 hover:text-ink", c.mono && "font-mono text-[13px]")}
                >
                  {c.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function isActive(path: string, item: Item) {
  return item.exact ? path === item.href : path === item.href || path.startsWith(`${item.href}/`);
}

function NavLink({
  item,
  count,
  active,
  onNavigate,
}: {
  item: Item;
  count?: number;
  active: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  const t = useTranslations("nav");
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm whitespace-nowrap transition-colors",
        active ? "bg-grey-100 font-medium text-ink" : "text-grey-700 hover:bg-grey-50 hover:text-ink",
      )}
    >
      <Icon
        className={cn("size-4 shrink-0", active ? "text-ink" : "text-grey-500 group-hover:text-ink")}
        strokeWidth={1.75}
        aria-hidden
      />
      <span className="flex-1">{t(item.label)}</span>
      {count ? (
        <span className="tnum rounded-full bg-human-soft px-1.5 text-[11px] leading-[18px] font-semibold text-human">
          {count}
        </span>
      ) : null}
    </Link>
  );
}

/** The first letter of a name, for the small workspace and person badges. */
const initial = (name: string | undefined) => (name?.trim()[0] ?? "").toUpperCase();

/** Who is signed in: their name, else their email, else the demo operator (demo) or a plain "You" (live). */
function usePerson() {
  const t = useTranslations("nav");
  const me = useMe().data;
  const demo = useIsDemo();
  const known = me?.name || me?.email || "";
  const name = known || (me ? (demo ? t("demoOperator") : t("you")) : "");
  return { name, known, role: me ? t(`roles.${me.role}`) : "" };
}

function WorkspaceMenu({ mode }: { mode: ShellMode }) {
  const work = mode === "work";
  const live = useIsLive();
  const { signOut } = useSession();
  const toast = useToast();
  const t = useTranslations("nav");
  const meQuery = useMe();
  const me = meQuery.data;
  const plan = useOrg().data?.plan;
  const demo = useIsDemo();
  const person = usePerson();
  const failed = meQuery.isError;
  const orgName = me?.orgName ?? "";
  // The demo's reviewer is a made-up persona; a live reviewer portal is the signed-in person's.
  const persona = work && demo;
  const name = persona ? t("reviewerName") : work ? t("reviewerPortal") : failed ? t("workspaceUnavailable") : orgName;
  // Until /v1/me answers there is no name to show, but the control still needs one.
  const label = name || t("workspaceLoading");
  return (
    <MenuRoot>
      <MenuTrigger
        className="flex min-h-10 w-full items-center gap-2.5 rounded-md px-2 py-1 text-left hover:bg-grey-50 data-[popup-open]:bg-grey-100"
        aria-label={t("switchWorkspace", { name: label })}
      >
        <span
          className={cn(
            "grid size-6 shrink-0 place-items-center rounded-md text-[11px] font-semibold text-paper",
            work ? "bg-human" : "bg-ink",
          )}
          aria-hidden
        >
          {work ? "R" : failed ? "!" : initial(orgName)}
        </span>
        {/* A long workspace name wraps to a second line rather than losing its end to the plan pill. */}
        <span
          className={cn(
            "line-clamp-2 min-w-0 flex-1 text-sm leading-tight font-medium break-words",
            failed && !work && "text-blocked",
          )}
        >
          {name}
        </span>
        {work || !plan ? null : (
          <span className="rounded-full bg-machine-soft px-1.5 text-[11px] leading-[18px] font-medium text-machine">
            {plan}
          </span>
        )}
        <ChevronsUpDown className="size-3.5 shrink-0 text-grey-500" aria-hidden />
      </MenuTrigger>
      <MenuPopup align="start" className="w-64">
        <MenuGroup>
          <MenuGroupLabel>{t("switchTo")}</MenuGroupLabel>
          <MenuLink href="/app">
            <span
              className="grid size-5 place-items-center rounded bg-ink text-[10px] font-semibold text-paper"
              aria-hidden
            >
              {initial(orgName)}
            </span>
            <span className="min-w-0 flex-1 truncate">{orgName}</span>
            {mode === "business" ? <Check className="size-3.5" aria-label={t("current")} /> : null}
          </MenuLink>
          <MenuLink href="/work">
            <span
              className="grid size-5 place-items-center rounded bg-human text-[10px] font-semibold text-paper"
              aria-hidden
            >
              R
            </span>
            <span className="flex-1">{t("reviewerPortal")}</span>
            {work ? <Check className="size-3.5" aria-label={t("current")} /> : null}
          </MenuLink>
          {/* Building agents and packs is part of the live workspace only. */}
          {live ? (
            <MenuLink href="/studio">
              <span
                className="grid size-5 place-items-center rounded bg-machine text-[10px] font-semibold text-paper"
                aria-hidden
              >
                S
              </span>
              <span className="flex-1">{t("developerStudio")}</span>
              {mode === "studio" ? <Check className="size-3.5" aria-label={t("current")} /> : null}
            </MenuLink>
          ) : null}
        </MenuGroup>
        <MenuSeparator />
        <LanguageMenuItems />
        <MenuSeparator />
        <MenuGroup>
          <MenuGroupLabel>{t("groups.account")}</MenuGroupLabel>
          <div className="truncate px-2.5 pb-1.5 text-sm text-grey-700">
            {demo ? t("signedInAs") : person.known ? t("signedInAsUser", { who: person.known }) : t("signedIn")}
          </div>
          <MenuItem onClick={() => void signOut().catch(() => toast(t("signOutFailed"), t("tryAgain"), "blocked"))}>
            <LogOut className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
            {t("signOut")}
          </MenuItem>
        </MenuGroup>
      </MenuPopup>
    </MenuRoot>
  );
}

/** Badge counts come from the cached lists, so they move when an approval or a claim does. None while loading. */
function useNavCounts(mode: ShellMode): Record<string, number | undefined> {
  const approvals = useApprovals(mode === "business");
  const memory = useMemory(mode === "business");
  const tasks = useEligibleTasks(mode === "work");
  return {
    "/app/approvals": approvals.data?.filter((a) => a.status === "PENDING").length,
    "/app/memory": memory.data?.filter((m) => m.state === "CANDIDATE").length,
    "/work": tasks.data?.length,
  };
}

function NavGroups({ mode, path, onNavigate }: { mode: ShellMode; path: string; onNavigate?: () => void }) {
  const counts = useNavCounts(mode);
  const t = useTranslations("nav.groups");
  const groups = navFor(mode, useIsLive());
  // The sidebar and the drawer both render this list; each needs its own ids.
  const uid = useId();
  return groups.map((g, i) => {
    const labelId = g.label ? `${uid}-${g.label}` : undefined;
    return (
      <div key={g.label ?? i} className={cn(i > 0 && "mt-3 border-t border-rule pt-3")}>
        {g.label ? (
          <div id={labelId} className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted uppercase">
            {t(g.label)}
          </div>
        ) : null}
        <ul aria-labelledby={labelId} className="space-y-0.5">
          {g.items.map((item) => (
            <li key={item.href}>
              <NavLink item={item} count={counts[item.href]} active={isActive(path, item)} onNavigate={onNavigate} />
            </li>
          ))}
        </ul>
      </div>
    );
  });
}

/** The way back to the business workspace from the reviewer portal or the Studio. The business sidebar lists
 * the other areas in its own nav group instead. */
function SwitchWorkspaceLink({ mode, onNavigate }: { mode: ShellMode; onNavigate?: () => void }) {
  const t = useTranslations("nav");
  if (mode === "business") return null;
  return (
    <Link
      href="/app"
      onClick={onNavigate}
      className="flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm text-grey-700 hover:bg-grey-50 hover:text-ink"
    >
      <ArrowLeftRight className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
      {t("businessWorkspace")}
    </Link>
  );
}

/** What is simulated here: the whole seeded demo, or a live workspace's sandbox apps and billing. Shown once,
 * in the sidebar (and the drawer), so page headers stay clear; figures that are simulated carry their own
 * inline tag. Below lg the sidebar is hidden, so SimulationStrip carries the label. */
function SimulationBadge() {
  const t = useTranslations("nav");
  const me = useMe();
  const demo = useIsDemo();
  if (!me.data) return null;
  return (
    <Tooltip label={demo ? t("demoTooltip") : t("sandboxTooltip")} side="top">
      <button
        type="button"
        className="mb-2 flex w-full items-center rounded-md border border-dashed border-sim/40 bg-sim-soft px-2.5 py-1.5 text-left text-xs leading-snug text-sim"
      >
        {demo ? t("demoBadge") : t("sandboxBadge")}
      </button>
    </Tooltip>
  );
}

/** The same label as a thin strip under the top bar below lg, where the sidebar is not on screen. */
function SimulationStrip() {
  const t = useTranslations("nav");
  const me = useMe();
  const demo = useIsDemo();
  if (!me.data) return null;
  return (
    <div
      title={demo ? t("demoTooltip") : t("sandboxTooltip")}
      className="border-t border-sim/20 bg-sim-soft px-4 py-1 text-xs leading-snug text-sim sm:px-6 lg:hidden"
    >
      {demo ? t("demoBadge") : t("sandboxBadge")}
    </div>
  );
}

function Sidebar({ mode, path }: { mode: ShellMode; path: string }) {
  const work = mode === "work";
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const t = useTranslations("nav");
  const person = usePerson();
  const demo = useIsDemo();
  const persona = work && demo;
  return (
    <aside className="hidden w-[248px] shrink-0 border-r border-rule bg-paper lg:block">
      <div className="sticky top-0 flex h-dvh flex-col">
        <div className="px-3 pt-3">
          <WorkspaceMenu mode={mode} />
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="mt-2 flex h-9 w-full items-center gap-2 rounded-md border border-rule bg-paper px-2.5 text-sm text-grey-500 hover:border-grey-300"
          >
            <Search className="size-4" strokeWidth={1.75} aria-hidden />
            <span className="flex-1 text-left">{t("find")}</span>
            <kbd className="rounded border border-rule px-1.5 font-sans text-[11px] text-grey-500">/</kbd>
          </button>
        </div>
        <nav aria-label={t("main")} className="mt-3 flex-1 space-y-1 overflow-y-auto px-3">
          <NavGroups mode={mode} path={path} />
        </nav>
        <div className="border-t border-rule p-3">
          <SimulationBadge />
          <SwitchWorkspaceLink mode={mode} />
          <div className="flex items-center gap-2.5 px-2.5 py-1.5">
            <span
              className="grid size-6 place-items-center rounded-full bg-grey-100 text-[11px] font-semibold"
              aria-hidden
            >
              {persona ? "R" : initial(person.name)}
            </span>
            <div className="min-w-0 text-xs leading-tight">
              <div className="truncate font-medium text-ink">{persona ? t("reviewerName") : person.name}</div>
              {/* In the reviewer portal everyone works as a reviewer, whatever their workspace role. */}
              <div className="truncate text-muted">
                {persona ? t("reviewerRole") : work ? t("roles.reviewer") : person.role}
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Below lg the sidebar becomes a drawer from the left, opened from the top bar. */
function MobileNav({ mode, path }: { mode: ShellMode; path: string }) {
  const open = useUi((s) => s.drawerOpen);
  const setOpen = useUi((s) => s.setDrawerOpen);
  const t = useTranslations("nav");
  const close = () => setOpen(false);

  // Any page change closes it, including browser back and links in the workspace menu.
  // Store state outlives navigation, so this runs in an effect, never during render.
  useEffect(() => {
    setOpen(false);
  }, [path, setOpen]);

  // The drawer only exists below lg; growing the window past it must not leave a hidden modal open.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 64rem)");
    const onChange = () => wide.matches && setOpen(false);
    wide.addEventListener("change", onChange);
    return () => wide.removeEventListener("change", onChange);
  }, [setOpen]);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        aria-label={t("openNavigation")}
        className="-ml-2.5 grid size-10 shrink-0 place-items-center rounded-md text-grey-700 hover:bg-grey-100 data-[popup-open]:bg-grey-100 lg:hidden"
      >
        <MenuIcon className="size-[18px]" strokeWidth={1.75} aria-hidden />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-ink/25 transition-opacity duration-200 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 motion-reduce:transition-none lg:hidden" />
        <Dialog.Popup className="fixed inset-y-0 left-0 z-50 flex w-[min(288px,calc(100vw-3rem))] flex-col border-r border-rule bg-paper shadow-[0_8px_28px_rgb(17_17_17/0.12)] transition-transform duration-200 ease-out outline-none data-[ending-style]:-translate-x-full data-[starting-style]:-translate-x-full motion-reduce:transition-none lg:hidden">
          <Dialog.Title className="sr-only">{t("navigation")}</Dialog.Title>
          <div className="flex items-center gap-1 px-3 pt-3">
            {/* A pick in the workspace menu closes the drawer even when it links to the current page. */}
            <div className="min-w-0 flex-1" onClickCapture={(e) => (e.target as HTMLElement).closest("a") && close()}>
              <WorkspaceMenu mode={mode} />
            </div>
            <Dialog.Close
              aria-label={t("closeNavigation")}
              className="grid size-10 shrink-0 place-items-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-ink"
            >
              <X className="size-4" aria-hidden />
            </Dialog.Close>
          </div>
          <nav aria-label={t("main")} className="mt-3 flex-1 space-y-1 overflow-y-auto px-3">
            <NavGroups mode={mode} path={path} onNavigate={close} />
          </nav>
          <div className="border-t border-rule p-3">
            <SimulationBadge />
            <SwitchWorkspaceLink mode={mode} onNavigate={close} />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function TopBar({ mode, path }: { mode: ShellMode; path: string }) {
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const t = useTranslations("nav");
  return (
    <div className="sticky top-0 z-20 border-b border-rule bg-paper/90 backdrop-blur">
      <header className="flex h-14 items-center gap-2 px-4 sm:gap-3 sm:px-6 lg:px-8">
        <MobileNav mode={mode} path={path} />
        {/* Below lg the logo and the icon buttons are tap targets of 40px, whatever the size of their glyph. */}
        <Link
          href={HOME[mode]}
          className="flex h-10 shrink-0 items-center rounded-md px-1.5 hover:bg-grey-100 lg:hidden"
          aria-label={t("home")}
        >
          <Mark trim className="h-3.5 text-ink" title="" />
        </Link>
        <Breadcrumbs path={path} mode={mode} />
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            aria-label={t("find")}
            className="grid size-10 place-items-center rounded-md text-grey-700 hover:bg-grey-100 lg:hidden"
          >
            <Search className="size-4" strokeWidth={1.75} aria-hidden />
          </button>
          {mode !== "business" ? null : (
            <>
              <Link
                href="/app/marketplace"
                className="hidden h-8 items-center gap-1.5 rounded-md px-2.5 text-sm text-grey-700 hover:bg-grey-100 hover:text-ink sm:inline-flex"
              >
                <LayoutGrid className="size-4" strokeWidth={1.75} aria-hidden />
                {t("browsePacks")}
              </Link>
              <StartRunMenu />
            </>
          )}
        </div>
      </header>
      <SimulationStrip />
    </div>
  );
}

/** Lists the hired packs from the API, so a pack hired during the demo appears here at once. */
export function StartRunMenu() {
  const t = useTranslations("nav");
  const hired = (usePacks().data ?? []).filter((p) => p.installed);
  return (
    <MenuRoot>
      {/* On a phone the button is its icon, so the page title in the top bar is not cut short. */}
      <MenuTrigger className="inline-flex size-10 items-center justify-center gap-1.5 rounded-md bg-ink text-sm font-medium whitespace-nowrap text-paper hover:bg-grey-900 data-[popup-open]:bg-grey-900 sm:h-8 sm:w-auto sm:px-3">
        <Plus className="size-4" strokeWidth={2} aria-hidden />
        <span className="sr-only sm:not-sr-only">{t("startRun")}</span>
      </MenuTrigger>
      <MenuPopup className="w-72">
        <MenuLabel>{t("choosePack")}</MenuLabel>
        {hired.map((pack) => (
          <MenuLink key={pack.slug} href={`/app/runs/new?pack=${pack.slug}`}>
            <PackIcon slug={pack.slug} className="size-6 [&_svg]:size-3" />
            {pack.name}
          </MenuLink>
        ))}
        <MenuSeparator />
        <MenuLink href="/app/marketplace">
          <LayoutGrid className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
          {t("hireAnother")}
        </MenuLink>
        <div className="px-2.5 pt-1.5 pb-1 text-xs text-muted">{t("startHelp")}</div>
      </MenuPopup>
    </MenuRoot>
  );
}

export function AppShell({ children, mode = "business" }: { children: ReactNode; mode?: ShellMode }) {
  const live = useIsLive();
  const path = usePathname();
  const t = useTranslations("nav");
  const pages = navFor(mode, live)
    .flatMap((g) => g.items)
    .map(({ href, label, icon }) => ({ href, label: t(label), icon }));
  return (
    <ClockProvider live={live}>
      {/* A page with its own heading is named once: the top bar's single crumb hides (a trail of crumbs stays). */}
      <div className="flex min-h-dvh [&:has(main_h1)_.page-crumb]:hidden">
        <Sidebar mode={mode} path={path} />
        <CommandPalette pages={pages} />
        <div className="min-w-0 flex-1">
          <TopBar mode={mode} path={path} />
          <main id="main" className="px-4 py-6 sm:px-6 lg:px-8 lg:py-7">
            <div className="mx-auto max-w-[2000px]">{children}</div>
          </main>
        </div>
      </div>
    </ClockProvider>
  );
}
