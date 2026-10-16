import type { TourName } from "./tours";

/** Whether a tour has been finished or skipped, kept in localStorage as `nm.tour.<name>.v1` = "done". */

type SeenStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const DONE = "done";

export const seenKey = (name: TourName) => `nm.tour.${name}.v1`;

// Tours finished or skipped in this page session. When storage refuses (private mode, blocked site data) this is
// what keeps a tour from starting again on the next visit to its page.
const session = new Set<TourName>();
// Tours that started by themselves in this page session. One left half way (browser back) does not start again
// until the next session; only finishing or skipping it marks it seen for good.
const started = new Set<TourName>();

export const startedThisSession = (name: TourName): boolean => started.has(name);

export function markStarted(name: TourName): void {
  started.add(name);
}

function localStore(): SeenStorage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function isSeen(name: TourName, storage: SeenStorage | undefined = localStore()): boolean {
  if (session.has(name)) return true;
  try {
    return storage?.getItem(seenKey(name)) === DONE;
  } catch {
    return false;
  }
}

export function markSeen(name: TourName, storage: SeenStorage | undefined = localStore()): void {
  session.add(name);
  try {
    storage?.setItem(seenKey(name), DONE);
  } catch {
    // The session set above still holds it.
  }
}

export function reset(name: TourName, storage: SeenStorage | undefined = localStore()): void {
  session.delete(name);
  started.delete(name);
  try {
    storage?.removeItem(seenKey(name));
  } catch {
    // Nothing was stored that could be removed.
  }
}

export const seen = { isSeen, markSeen, reset, startedThisSession, markStarted };
