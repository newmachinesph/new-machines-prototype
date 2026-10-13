"use client";

import { createContext, type ReactNode, useContext, useSyncExternalStore } from "react";
import { NOW } from "./format";

/** How often a live workspace's relative times and countdowns move on. */
const TICK_MS = 30_000;

// One shared ticker for the whole page, running only while a live workspace is on screen.
let current = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!timer) {
    current = Date.now();
    timer = setInterval(() => {
      current = Date.now();
      listeners.forEach((l) => l());
    }, TICK_MS);
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}
const idle = () => () => {};
const pinned = () => Date.parse(NOW);

const Clock = createContext<string>(NOW);

/**
 * The "now" every relative time and countdown is measured from. The demo workspace keeps the prototype's
 * pinned NOW so its fixtures read the same on every screen; a live workspace follows the real clock.
 */
export function ClockProvider({ live, children }: { live: boolean; children: ReactNode }) {
  const at = useSyncExternalStore(live ? subscribe : idle, () => current, pinned);
  return <Clock.Provider value={live ? new Date(at).toISOString() : NOW}>{children}</Clock.Provider>;
}

/** The current "now" as an ISO string: the real clock in a live workspace, the pinned NOW otherwise. */
export const useNow = () => useContext(Clock);
