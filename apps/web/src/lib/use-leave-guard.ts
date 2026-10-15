"use client";

import { useTranslations } from "next-intl";
import { useEffect } from "react";

/**
 * The link a click is about to follow, when it is one to ask about: a plain left click on a same-origin link that
 * opens in this tab, is not a download, and is not a jump within the page.
 */
function guardedLink(e: MouseEvent): HTMLAnchorElement | null {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return null;
  const link = e.target instanceof Element ? e.target.closest("a[href]") : null;
  if (!(link instanceof HTMLAnchorElement)) return null;
  if ((link.target && link.target !== "_self") || link.hasAttribute("download")) return null;
  const to = new URL(link.href, window.location.href);
  if (to.origin !== window.location.origin) return null;
  if (to.hash && to.pathname === window.location.pathname && to.search === window.location.search) return null;
  return link;
}

/**
 * Asks before unsaved work is lost: on reload or tab close (`beforeunload`), and before an in-app link is followed
 * (sidebar, breadcrumbs, menus), which the browser's own prompt does not cover. A "no" stops the link.
 */
export function useLeaveGuard(dirty: boolean) {
  const t = useTranslations("common");
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    const ask = (e: MouseEvent) => {
      if (!guardedLink(e)) return;
      if (window.confirm(t("leaveUnsaved"))) return;
      e.preventDefault();
      // The link's own click handler (a Next.js Link) must not run either.
      e.stopImmediatePropagation();
    };
    window.addEventListener("beforeunload", warn);
    // The capture phase on the document runs before React and the link see the click.
    document.addEventListener("click", ask, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", ask, true);
    };
  }, [dirty, t]);
}
