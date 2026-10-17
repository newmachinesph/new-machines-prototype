"use client";

import { useTranslations } from "next-intl";

/** The plans the messages name (`nav.plans`); the API's plan names are compared lower-cased. */
const PLANS = ["trial", "pro"] as const;
type PlanKey = (typeof PLANS)[number];
const planKey = (plan: string): PlanKey | undefined => PLANS.find((p) => p === plan.toLowerCase());

/**
 * A plan's name in the interface language: the API sends English names ("Trial"), which the messages translate.
 * Any other plan shows as the API sent it; no plan gives undefined.
 */
export function usePlanName(): PlanName {
  const t = useTranslations("nav.plans");
  return ((plan: string | undefined) => {
    if (!plan) return undefined;
    const known = planKey(plan);
    return known ? t(known) : plan;
  }) as PlanName;
}

type PlanName = {
  (plan: string): string;
  (plan: string | undefined): string | undefined;
};
