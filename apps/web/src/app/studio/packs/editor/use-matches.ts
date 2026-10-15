import { useCallback, useSyncExternalStore } from "react";

const matchesNow = (query: string) =>
  typeof window.matchMedia === "function" ? window.matchMedia(query).matches : true;

/**
 * Whether the viewport matches a media query. On the server, and where matchMedia is missing (tests), it
 * matches, so the editor renders its full layout first and narrows once the browser says so.
 */
export function useMatches(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => matchesNow(query),
    () => true,
  );
}
