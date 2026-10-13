"use client";

import { Dialog } from "@base-ui/react/dialog";
import {
  Activity,
  Bot,
  Brain,
  Building2,
  ChevronRight,
  FileCheck2,
  FileCode2,
  Gauge,
  LogOut,
  Menu as MenuIcon,
  Plug,
  Receipt,
  ScrollText,
  ShieldAlert,
  Store,
  UserCog,
  Users,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { Lockup } from "@/design-system/logo/Lockup";
import { Mark } from "@/design-system/logo/Mark";
import { ApiError } from "@/lib/api/errors";
import { env } from "@/lib/env";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { useMe } from "@/lib/queries/ops";
import type { OpsRole } from "@/lib/types";
import { useToast } from "./base";
import { Skeleton } from "./skeleton";
import { Button } from "./ui";

export type NavItem = { href: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

/** The console's sections. Keep CONSOLE_AREAS in lib/auth/next-path.ts in step. */
export const NAV: NavGroup[] = [
  { label: "Overview", items: [{ href: "/command", label: "Command center", icon: Gauge }] },
  {
    label: "Customers",
    items: [
      { href: "/tenants", label: "Tenants", icon: Building2 },
      { href: "/runs", label: "Runs", icon: Workflow },
      { href: "/billing", label: "Billing", icon: Receipt },
    ],
  },
  {
    label: "Catalog",
    items: [
      { href: "/marketplace", label: "Marketplace", icon: Store },
      { href: "/connectors", label: "Connectors", icon: Plug },
    ],
  },
  {
    label: "Build",
    items: [
      { href: "/definitions", label: "Definitions", icon: FileCode2 },
      { href: "/agents", label: "Agents", icon: Bot },
      { href: "/contracts", label: "Work Contracts", icon: FileCheck2 },
      { href: "/memory", label: "Memory", icon: Brain },
    ],
  },
  {
    label: "People",
    items: [
      { href: "/workforce", label: "Workforce", icon: Users },
      { href: "/team", label: "Ops team", icon: UserCog },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/guardrails", label: "Guardrails", icon: ShieldAlert },
      { href: "/health", label: "System health", icon: Activity },
      { href: "/audit", label: "Audit log", icon: ScrollText },
    ],
  },
];

const isActive = (path: string, href: string) => path === href || path.startsWith(`${href}/`);

/** The nav entry a path belongs to, with its group, for the top bar's location. */
export function locate(path: string): { group: NavGroup; item: NavItem } | null {
  for (const group of NAV) {
    const item = group.items.find((i) => isActive(path, i.href));
    if (item) return { group, item };
  }
  return null;
}

const ROLE: Record<OpsRole, { label: string; className: string }> = {
  owner: { label: "Owner", className: "bg-ink text-paper" },
  admin: { label: "Admin", className: "bg-machine-soft text-machine" },
  support: { label: "Support, read only", className: "bg-grey-100 text-grey-700" },
};

/** The operator's ops role. Support is read-only: the API refuses its writes. */
export function RolePill({ role }: { role: OpsRole }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        ROLE[role].className,
      )}
    >
      {ROLE[role].label}
    </span>
  );
}

/* ── Sidebar: ink, so staff always know they are in the operator console ── */

function Brand() {
  return (
    <Link href="/command" className="block rounded-md px-2.5 py-1.5" aria-label="Operator console home">
      <Lockup trim className="h-8 w-auto text-paper" title="" />
      <span className="mt-2.5 block text-[13px] font-medium text-chrome-text">Operator console</span>
    </Link>
  );
}

function NavGroups({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return NAV.map((group) => (
    <div key={group.label} className="mt-5 first:mt-0">
      <h2 className="px-2.5 pb-1 text-xs text-chrome-muted">{group.label}</h2>
      <ul className="space-y-0.5">
        {group.items.map((item) => {
          const active = isActive(path, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm whitespace-nowrap transition-colors",
                  active
                    ? "bg-chrome-raise font-medium text-paper"
                    : "text-chrome-text hover:bg-chrome-raise/70 hover:text-paper",
                )}
              >
                <Icon
                  className={cn("size-4 shrink-0", active ? "text-paper" : "text-chrome-muted group-hover:text-paper")}
                  strokeWidth={1.75}
                  aria-hidden
                />
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  ));
}

function SidebarBody({ path, onNavigate, close }: { path: string; onNavigate?: () => void; close?: ReactNode }) {
  return (
    <>
      <div className="flex items-start justify-between gap-2 px-3 pt-4">
        <Brand />
        {close}
      </div>
      <nav aria-label="Console" className="mt-5 flex-1 overflow-y-auto px-3 pb-4">
        <NavGroups path={path} onNavigate={onNavigate} />
      </nav>
      <p className="border-t border-chrome-line px-5 py-3.5 text-xs leading-snug text-chrome-muted">
        Staff only. Every change is recorded in the audit log. Demo environment: tenants and data are synthetic.
      </p>
    </>
  );
}

function Sidebar({ path }: { path: string }) {
  return (
    <aside className="hidden w-[232px] shrink-0 bg-chrome text-chrome-text lg:block">
      <div className="sticky top-0 flex h-dvh flex-col">
        <SidebarBody path={path} />
      </div>
    </aside>
  );
}

/** Below lg the sidebar becomes a drawer from the left, opened from the top bar. */
function MobileNav({ path }: { path: string }) {
  // The drawer remembers the path it opened on, so any navigation (a link, browser back) closes it.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === path;
  const close = () => setOpenOn(null);

  // The drawer only exists below lg; growing the window past it must not leave a hidden modal open.
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 64rem)");
    const onChange = () => {
      if (wide.matches) setOpenOn(null);
    };
    wide.addEventListener("change", onChange);
    return () => wide.removeEventListener("change", onChange);
  }, []);

  return (
    <Dialog.Root open={open} onOpenChange={(o) => setOpenOn(o ? path : null)}>
      <Dialog.Trigger
        aria-label="Open navigation"
        className="-ml-1.5 grid size-8 shrink-0 place-items-center rounded-md text-grey-700 hover:bg-grey-100 data-[popup-open]:bg-grey-100 lg:hidden"
      >
        <MenuIcon className="size-[18px]" strokeWidth={1.75} aria-hidden />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-ink/40 transition-opacity duration-200 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 motion-reduce:transition-none lg:hidden" />
        <Dialog.Popup className="fixed inset-y-0 left-0 z-50 flex w-[min(272px,calc(100vw-3rem))] flex-col bg-chrome text-chrome-text shadow-[0_8px_28px_rgb(17_17_17/0.24)] transition-transform duration-200 ease-out outline-none data-[ending-style]:-translate-x-full data-[starting-style]:-translate-x-full motion-reduce:transition-none lg:hidden">
          <Dialog.Title className="sr-only">Navigation</Dialog.Title>
          <SidebarBody
            path={path}
            onNavigate={close}
            close={
              <Dialog.Close
                aria-label="Close navigation"
                className="grid size-8 shrink-0 place-items-center rounded-md text-chrome-muted hover:bg-chrome-raise hover:text-paper"
              >
                <X className="size-4" aria-hidden />
              </Dialog.Close>
            }
          />
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* ── Top bar: where you are, which environment, who you are ── */

function Location({ path }: { path: string }) {
  const here = locate(path);
  if (!here) return null;
  const rest = path.slice(here.item.href.length).split("/").filter(Boolean);
  const deep = rest.length > 0;
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5 text-sm">
        <li className="hidden shrink-0 text-muted xl:block">{here.group.label}</li>
        <li className={cn("min-w-0 items-center gap-1.5", deep ? "hidden sm:flex" : "flex")}>
          <ChevronRight className="hidden size-3.5 shrink-0 text-grey-300 xl:block" aria-hidden />
          {deep ? (
            <Link href={here.item.href} className="truncate text-grey-700 hover:text-ink">
              {here.item.label}
            </Link>
          ) : (
            <span aria-current="page" className="truncate font-medium">
              {here.item.label}
            </span>
          )}
        </li>
        {deep ? (
          <li className="flex min-w-0 items-center gap-1.5">
            <ChevronRight className="hidden size-3.5 shrink-0 text-grey-300 sm:block" aria-hidden />
            <span aria-current="page" className="truncate font-mono text-[13px] font-medium">
              {safeDecode(rest.join("/"))}
            </span>
          </li>
        ) : null}
      </ol>
    </nav>
  );
}

/** A malformed `%` sequence in the URL must not take the shell down. */
function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** A label, not a control: the sidebar footer says what the demo environment is. */
function EnvironmentBadge() {
  return (
    <span className="inline-block shrink-0 rounded-full border border-dashed border-sim/40 bg-sim-soft px-2.5 py-1 text-xs whitespace-nowrap text-sim">
      Demo <span className="hidden sm:inline">environment</span>
    </span>
  );
}

function Operator() {
  const me = useMe();
  const { signOut } = useSession();
  const toast = useToast();
  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {me.data ? (
        <>
          <span className="hidden max-w-[24ch] truncate text-sm text-grey-700 md:block" title={me.data.email}>
            {me.data.email}
          </span>
          <RolePill role={me.data.role} />
        </>
      ) : me.isPending ? (
        <Skeleton className="h-5 w-40" />
      ) : null}
      <Button
        variant="ghost"
        className="h-8 px-2 md:px-2.5"
        aria-label="Sign out"
        onClick={() => void signOut().catch(() => toast("Sign-out failed", "Try again in a moment.", "blocked"))}
      >
        <LogOut className="size-4 text-grey-500" strokeWidth={1.75} aria-hidden />
        <span className="hidden md:inline">Sign out</span>
      </Button>
    </div>
  );
}

function TopBar({ path }: { path: string }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-rule bg-paper/95 px-4 backdrop-blur sm:px-6 lg:px-8">
      <MobileNav path={path} />
      <Link href="/command" className="hidden shrink-0 sm:block lg:hidden" aria-label="Operator console home">
        <Mark trim className="h-3 text-ink" title="" />
      </Link>
      <Location path={path} />
      <div className="ml-auto flex shrink-0 items-center gap-3">
        <EnvironmentBadge />
        <Operator />
      </div>
    </header>
  );
}

/** Shown instead of the page when the API says this account is not on the ops allowlist. */
function NoAccess() {
  const { user, signOut } = useSession();
  return (
    <div role="alert" className="panel mx-auto mt-10 max-w-xl p-6">
      <h1 className="h-section">You don&apos;t have operator access</h1>
      <p className="mt-2 text-sm leading-relaxed text-grey-700">
        {user?.email ? <>{user.email} is </> : "This account is "}not on the ops allowlist. Ask an owner to add you, or
        sign in with your staff account.
      </p>
      <div className="mt-5">
        <Button variant="secondary" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    </div>
  );
}

/** The operator console chrome: ink sidebar (a drawer below lg), top bar with environment and operator, page body. */
export function OpsShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const me = useMe();
  return (
    <div className="flex min-h-dvh">
      <Sidebar path={path} />
      <div className="min-w-0 flex-1">
        {env.NEXT_PUBLIC_AUTH_MOCK ? (
          <p className="bg-sim px-4 py-1 text-center text-xs text-paper">
            Mock sign-in is on. This build is for tests only and must never be deployed.
          </p>
        ) : null}
        <TopBar path={path} />
        <main id="main" tabIndex={-1} className="px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-7">
          <div className="mx-auto max-w-[1600px]">
            <OperatorGate me={me}>{children}</OperatorGate>
          </div>
        </main>
      </div>
    </div>
  );
}

/** Pages render only once the API confirms an operator, so a non-operator never sees console content. */
function OperatorGate({ me, children }: { me: ReturnType<typeof useMe>; children: ReactNode }) {
  if (me.data) return children;
  if (me.isPending) return <Skeleton className="h-64" />;
  if (me.error instanceof ApiError && me.error.status === 403) return <NoAccess />;
  return (
    <div className="panel mx-auto mt-10 max-w-xl p-6">
      <h1 className="h-section">Operator access can&apos;t be checked right now</h1>
      <p role="alert" className="mt-2 text-sm leading-relaxed text-grey-700">
        The API did not answer. Check that it is running, then try again.
      </p>
      <div className="mt-5">
        <Button variant="secondary" onClick={() => void me.refetch()}>
          Try again
        </Button>
      </div>
    </div>
  );
}
