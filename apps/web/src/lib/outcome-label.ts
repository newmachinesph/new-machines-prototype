import { useTranslations } from "next-intl";
import { useCallback } from "react";

/** The outcomes every step type routes (apps/api/app/studio_build.py ROUTES, and the run projection's failure routes). */
const KNOWN_OUTCOMES = [
  "next",
  "ok",
  "denied",
  "error",
  "resolved",
  "rejected",
  "timeout",
  "granted",
  "pass",
  "fail",
  "blocked",
  "failed",
] as const;
type KnownOutcome = (typeof KNOWN_OUTCOMES)[number];
const isKnown = (code: string): code is KnownOutcome => (KNOWN_OUTCOMES as readonly string[]).includes(code);
/** A failure stub's edge carries every route into it, joined (apps/web/src/lib/terminal-stubs.ts). */
const JOIN = " · ";

/** A route name the builder chose ("human_review") as words: "Human review". */
const asWords = (code: string) => {
  const words = code.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

type OutcomeLabel = {
  (label: string): string;
  (label: string | undefined): string | undefined;
};

/**
 * An outcome as a person reads it on a canvas: a fixed outcome in the viewer's language ("granted" reads
 * "Approved"), a decision's own route name as words. A joined label translates route by route; an empty one stays
 * as it is.
 */
export function useOutcomeLabel(): OutcomeLabel {
  const t = useTranslations("outcomes");
  const label = useCallback(
    (value: string | undefined) => {
      if (!value) return value;
      return value
        .split(JOIN)
        .map((code) => (isKnown(code) ? t(code) : asWords(code)))
        .join(JOIN);
    },
    [t],
  );
  return label as OutcomeLabel;
}
