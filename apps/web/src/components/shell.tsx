"use client";

import { Dialog } from "@base-ui/react/dialog";
import {
  ArrowLeftRight,
  Bot,
  Brain,
  Check,
  ChevronRight,
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
import { useEffect, type ReactNode } from "react";
import { Mark } from "@/design-system/logo/Mark";
import { useSession } from "@/lib/auth/session";
import { ClockProvider } from "@/lib/clock";
import { cn } from "@/lib/cn";
import { useAgentName, usePackName, usePacks } from "@/lib/queries/catalog";
import { useIsDemo, useIsLive, useMe } from "@/lib/queries/me";
import { useOrg } from "@/lib/queries/org";
import { useEligibleTasks } from "@/lib/queries/tasks";
import { useApprovals, useMemory } from "@/lib/queries/workspace";
import { useUi } from "@/stores/ui";
import {
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
  | "earnings";
type CrumbKey = "crumbDeliverable" | "crumbHire" | "crumbStartRun";

/** `label` is a key under `nav`. */
type Item = { href: string; label: PageKey; icon: LucideIcon; exact?: boolean; liveOnly?: boolean };

const BUSINESS_NAV: Item[][] = [
  [
    { href: "/app", label: "overview", icon: House, exact: true },
    { href: "/app/runs", label: "runs", icon: Workflow },
    { href: "/app/approvals", label: "approvals", icon: ListChecks },
    { href: "/app/marketplace", label: "marketplace", icon: Store },
    { href: "/app/agents", label: "agents", icon: Bot },
  ],
  [
    { href: "/app/memory", label: "memory", icon: Brain },
    { href: "/app/connections", label: "connections", icon: Plug },
    { href: "/app/reviewers", label: "reviewers", icon: UserCheck, liveOnly: true },
  ],
  [
    { href: "/app/usage", label: "usage", icon: CircleDollarSign },
    { href: "/app/settings", label: "settings", icon: Settings },
  ],
];

const WORK_NAV: Item[][] = [
  [
    { href: "/work", label: "availableTasks", icon: Inbox, exact: true },
    { href: "/work/earnings", label: "earnings", icon: Wallet },
  ],
];

/** The pages a workspace offers, in the sidebar and the command palette alike. Reviewer management exists only
 * in a live workspace, so the demo's navigation is unchanged. */
const navFor = (work: boolean, live: boolean): Item[][] =>
  (work ? WORK_NAV : BUSINESS_NAV).map((g) => g.filter((item) => live || !item.liveOnly));

type Crumb = { label: string; href?: string; mono?: boolean };

// Path segments that name a sub-page rather than a record; values are keys under `nav`.
const SUBPAGE: Record<string, CrumbKey> = { evidence: "crumbDeliverable", install: "crumbHire", new: "crumbStartRun" };

function crumbsFor(
  path: string,
  work: boolean,
  recordName: string | undefined,
  t: (key: PageKey | CrumbKey) => string,
): Crumb[] {
  const parts = path.split("/").filter(Boolean);
  const nav = (work ? WORK_NAV : BUSINESS_NAV).flat();
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
    } else if (SUBPAGE[seg]) {
      out.push({ label: t(SUBPAGE[seg]), href });
    } else {
      out.push(recordName ? { label: recordName, href } : { label: seg, href, mono: true });
    }
  });
  if (!out.length) out.push({ label: t(work ? "availableTasks" : "overview") });
  return out;
}

function Breadcrumbs({ path, work }: { path: string; work: boolean }) {
  const slug = /^\/app\/marketplace\/([^/]+)/.exec(path)?.[1];
  const agentId = /^\/app\/agents\/([^/]+)/.exec(path)?.[1];
  const packName = usePackName(slug);
  const agentName = useAgentName(agentId);
  const t = useTranslations("nav");
  const crumbs = crumbsFor(path, work, packName ?? agentName, t);
  return (
    <nav aria-label={t("breadcrumb")} className="min-w-0">
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

function WorkspaceMenu({ work }: { work: boolean }) {
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
  const name = work ? t("reviewerName") : failed ? t("workspaceUnavailable") : orgName;
  // Until /v1/me answers there is no name to show, but the control still needs one.
  const label = name || t("workspaceLoading");
  return (
    <MenuRoot>
      <MenuTrigger
        className="flex h-10 w-full items-center gap-2.5 rounded-md px-2 text-left hover:bg-grey-50 data-[popup-open]:bg-grey-100"
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
        <span className={cn("min-w-0 flex-1 truncate text-sm font-medium", failed && !work && "text-blocked")}>
          {name}
        </span>
        {work || !plan ? null : (
          <span className="rounded-full bg-machine-soft px-1.5 text-[11px] leading-[18px] font-medium text-machine">
            {plan}
          </span>
        )}
        <ChevronsUpDown className="size-3.5 text-grey-500" aria-hidden />
      </MenuTrigger>
      <MenuPopup align="start" className="w-64">
        <MenuLabel>
          {demo ? t("signedInAs") : person.known ? t("signedInAsUser", { who: person.known }) : t("signedIn")}
        </MenuLabel>
        <MenuLink href="/app">
          <span
            className="grid size-5 place-items-center rounded bg-ink text-[10px] font-semibold text-paper"
            aria-hidden
          >
            {initial(orgName)}
          </span>
          <span className="min-w-0 flex-1 truncate">{orgName}</span>
          {work ? null : <Check className="size-3.5" aria-label={t("current")} />}
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
        <MenuSeparator />
        <LanguageMenuItems />
        <MenuSeparator />
        <MenuItem onClick={() => void signOut().catch(() => toast(t("signOutFailed"), t("tryAgain"), "blocked"))}>
          <LogOut className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
          {t("signOut")}
        </MenuItem>
      </MenuPopup>
    </MenuRoot>
  );
}

/** Badge counts come from the cached lists, so they move when an approval or a claim does. None while loading. */
function useNavCounts(work: boolean): Record<string, number | undefined> {
  const approvals = useApprovals(!work);
  const memory = useMemory(!work);
  const tasks = useEligibleTasks(work);
  return {
    "/app/approvals": approvals.data?.filter((a) => a.status === "PENDING").length,
    "/app/memory": memory.data?.filter((m) => m.state === "CANDIDATE").length,
    "/work": tasks.data?.length,
  };
}

function NavGroups({ work, path, onNavigate }: { work: boolean; path: string; onNavigate?: () => void }) {
  const counts = useNavCounts(work);
  const groups = navFor(work, useIsLive());
  return groups.map((g, i) => (
    <ul key={i} className={cn("space-y-0.5", i > 0 && "mt-2 border-t border-rule pt-2")}>
      {g.map((item) => (
        <li key={item.href}>
          <NavLink item={item} count={counts[item.href]} active={isActive(path, item)} onNavigate={onNavigate} />
        </li>
      ))}
    </ul>
  ));
}

function SwitchWorkspaceLink({ work, onNavigate }: { work: boolean; onNavigate?: () => void }) {
  const t = useTranslations("nav");
  return (
    <Link
      href={work ? "/app" : "/work"}
      onClick={onNavigate}
      className="flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm text-grey-700 hover:bg-grey-50 hover:text-ink"
    >
      <ArrowLeftRight className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
      {work ? t("businessWorkspace") : t("reviewerPortal")}
    </Link>
  );
}

function Sidebar({ work, path }: { work: boolean; path: string }) {
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const t = useTranslations("nav");
  const person = usePerson();
  return (
    <aside className="hidden w-[248px] shrink-0 border-r border-rule bg-paper lg:block">
      <div className="sticky top-0 flex h-dvh flex-col">
        <div className="px-3 pt-3">
          <WorkspaceMenu work={work} />
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
          <NavGroups work={work} path={path} />
        </nav>
        <div className="border-t border-rule p-3">
          <SwitchWorkspaceLink work={work} />
          <div className="mt-1 flex items-center gap-2.5 px-2.5 py-1.5">
            <span
              className="grid size-6 place-items-center rounded-full bg-grey-100 text-[11px] font-semibold"
              aria-hidden
            >
              {work ? "R" : initial(person.name)}
            </span>
            <div className="min-w-0 text-xs leading-tight">
              <div className="truncate font-medium text-ink">{work ? t("reviewerName") : person.name}</div>
              <div className="truncate text-muted">{work ? t("reviewerRole") : person.role}</div>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Below lg the sidebar becomes a drawer from the left, opened from the top bar. */
function MobileNav({ work, path }: { work: boolean; path: string }) {
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
        className="-ml-1.5 grid size-8 shrink-0 place-items-center rounded-md text-grey-700 hover:bg-grey-100 data-[popup-open]:bg-grey-100 lg:hidden"
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
              <WorkspaceMenu work={work} />
            </div>
            <Dialog.Close
              aria-label={t("closeNavigation")}
              className="grid size-8 shrink-0 place-items-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-ink"
            >
              <X className="size-4" aria-hidden />
            </Dialog.Close>
          </div>
          <nav aria-label={t("main")} className="mt-3 flex-1 space-y-1 overflow-y-auto px-3">
            <NavGroups work={work} path={path} onNavigate={close} />
          </nav>
          <div className="border-t border-rule p-3">
            <SwitchWorkspaceLink work={work} onNavigate={close} />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** What is simulated here: the whole seeded demo, or a live workspace's sandbox apps and billing. */
function SimulationBadge() {
  const t = useTranslations("nav");
  const me = useMe();
  const demo = useIsDemo();
  if (!me.data) return null;
  return (
    <Tooltip label={demo ? t("demoTooltip") : t("sandboxTooltip")} side="bottom">
      <button
        type="button"
        className="hidden items-center rounded-full border border-dashed border-sim/40 bg-sim-soft px-2.5 py-1 text-xs text-sim md:inline-flex"
      >
        {demo ? t("demoBadge") : t("sandboxBadge")}
      </button>
    </Tooltip>
  );
}

function TopBar({ work, path }: { work: boolean; path: string }) {
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const t = useTranslations("nav");
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-rule bg-paper/90 px-4 backdrop-blur sm:px-6 lg:px-8">
      <MobileNav work={work} path={path} />
      <Link href={work ? "/work" : "/app"} className="shrink-0 lg:hidden" aria-label={t("home")}>
        <Mark trim className="h-3.5 text-ink" title="" />
      </Link>
      <Breadcrumbs path={path} work={work} />
      <div className="ml-auto flex items-center gap-2">
        <SimulationBadge />
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          aria-label={t("find")}
          className="grid size-8 place-items-center rounded-md text-grey-700 hover:bg-grey-100 lg:hidden"
        >
          <Search className="size-4" strokeWidth={1.75} aria-hidden />
        </button>
        {work ? null : (
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
  );
}

/** Lists the hired packs from the API, so a pack hired during the demo appears here at once. */
export function StartRunMenu() {
  const t = useTranslations("nav");
  const hired = (usePacks().data ?? []).filter((p) => p.installed);
  return (
    <MenuRoot>
      <MenuTrigger className="inline-flex h-8 items-center gap-1.5 rounded-md bg-ink px-3 text-sm font-medium text-paper hover:bg-grey-900 data-[popup-open]:bg-grey-900">
        <Plus className="size-4" strokeWidth={2} aria-hidden />
        {t("startRun")}
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

export function AppShell({ children, mode = "business" }: { children: ReactNode; mode?: "business" | "work" }) {
  const live = useIsLive();
  const path = usePathname();
  const work = mode === "work";
  const t = useTranslations("nav");
  const pages = navFor(work, live)
    .flat()
    .map(({ href, label, icon }) => ({ href, label: t(label), icon }));
  return (
    <ClockProvider live={live}>
      <div className="flex min-h-dvh">
        <Sidebar work={work} path={path} />
        <CommandPalette pages={pages} />
        <div className="min-w-0 flex-1">
          <TopBar work={work} path={path} />
          <main id="main" className="px-4 py-6 sm:px-6 lg:px-8 lg:py-7">
            <div className="mx-auto max-w-[2000px]">{children}</div>
          </main>
        </div>
      </div>
    </ClockProvider>
  );
}
