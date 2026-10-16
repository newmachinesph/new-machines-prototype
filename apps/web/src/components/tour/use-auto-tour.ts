"use client";

import { useEffect } from "react";
import { isSeen, markStarted, startedThisSession } from "@/lib/tour/seen";
import { autoStartEnabled, TOURS, type TourName } from "@/lib/tour/tours";
import { useTour } from "./tour-context";

/**
 * A query a page waits on before its tour starts has settled: it has data or an error, or it is not running at
 * all (disabled), so a tour is never held back forever by a query that will not load.
 */
export const isSettled = (q: { isPending: boolean; fetchStatus: string }) => !q.isPending || q.fetchStatus === "idle";

/**
 * Starts a tour when its page is ready: its data has loaded (so never over a skeleton) and its first target is on
 * the page. A replay asked for from another page starts here regardless. Otherwise it starts by itself once a
 * session; a tour finished or skipped before, or `NEXT_PUBLIC_TOURS=off`, keeps it from starting.
 */
export function useAutoTour(name: TourName, ready: boolean): void {
  const { start, pending, clearPending } = useTour();
  useEffect(() => {
    if (!ready) return;
    const first = TOURS[name][0];
    if (!first || !document.querySelector(first.selector)) return;
    if (pending?.name === name) {
      if (start(name, pending.opener)) clearPending();
      return;
    }
    if (!autoStartEnabled() || startedThisSession(name) || isSeen(name)) return;
    if (start(name)) markStarted(name);
  }, [name, ready, start, pending, clearPending]);
}
