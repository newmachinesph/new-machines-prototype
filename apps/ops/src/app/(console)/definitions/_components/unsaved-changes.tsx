"use client";

import { AlertDialog } from "@base-ui/react/alert-dialog";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { BACKDROP, MODAL } from "@/components/base";
import { Button } from "@/components/ui";

/** Where a plain click on a link would go inside the console, or null when it is not such a navigation. */
function inAppTarget(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null; // a new tab or window
  const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!(link instanceof HTMLAnchorElement) || link.hasAttribute("download")) return null;
  if (link.target && link.target !== "_self") return null;
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) return null; // another site: the browser's own prompt covers it
  const here = window.location;
  if (url.pathname === here.pathname && url.search === here.search) return null; // same page, maybe a #hash
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Keeps unpublished edits from being lost while `dirty`: closing or reloading the tab gets the browser's
 * "leave site?" prompt, and a click on any link inside the console (sidebar, back link, versions, references)
 * is held until the person confirms in the dialog `pending` drives. Browser Back is not intercepted.
 */
export function useLeaveGuard(dirty: boolean) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = ""; // older browsers show the prompt only when this is set
    };
    // Capture on the document runs before Next's Link handler, which listens on the React root below it.
    const click = (event: MouseEvent) => {
      const target = inAppTarget(event);
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      setPending(target);
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", click, true);
    };
  }, [dirty]);

  return {
    pending,
    stay: () => setPending(null),
    leave: () => {
      if (pending) router.push(pending);
      setPending(null);
    },
  };
}

/** A confirm dialog for throwing away unpublished edits. Nothing is saved, so there is no reason to give. */
export function DiscardDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <AlertDialog.Root open={open} onOpenChange={(next) => (next ? undefined : onCancel())}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={BACKDROP} />
        <AlertDialog.Popup className={MODAL}>
          <AlertDialog.Title className="text-base font-semibold">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-1.5 text-sm leading-relaxed text-grey-700">
            {children}
          </AlertDialog.Description>
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <AlertDialog.Close render={<Button variant="ghost" />}>Keep editing</AlertDialog.Close>
            <Button variant="destructive" onClick={onConfirm}>
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
