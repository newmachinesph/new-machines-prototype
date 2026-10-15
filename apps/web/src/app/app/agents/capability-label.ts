"use client";

import { useLocale, useTranslations } from "next-intl";
import { useCallback } from "react";

/** `finance.collections` as words when no label is published: "Finance collections". */
export function humaniseCapability(id: string): string {
  const words = id
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .split(/[._\-\s]+/)
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * A capability id as a plain label. The catalog publishes no labels, so the known ids are translated under
 * `agents.capability` and any other id falls back to its own words in English, or to the id itself elsewhere,
 * where half-English words would read worse than the id.
 */
export function useCapabilityLabel() {
  // Ids arrive from the API, so the keys are not known to the message types: look them up loosely.
  const english = useLocale() === "en";
  const t = useTranslations("agents.capability") as unknown as { (key: string): string; has(key: string): boolean };
  return useCallback(
    (id: string) => {
      const key = id.replace(/[^A-Za-z0-9]+/g, "_");
      return t.has(key) ? t(key) : english ? humaniseCapability(id) : id;
    },
    [t, english],
  );
}
