"use client";

import { useTranslations } from "next-intl";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { KeyValues, Section } from "@/components/ui";
import { useOrg } from "@/lib/queries/org";
import { usePolicies } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";

/** The policies with a title of their own; any other name is shown as words. */
const POLICY_NAMES = ["tool_actions", "human_review", "spend_cap", "region"] as const;
type PolicyName = (typeof POLICY_NAMES)[number];
const isNamed = (name: string): name is PolicyName => (POLICY_NAMES as readonly string[]).includes(name);

/** A policy ref such as "tool_actions@1" is its name and version. */
export function splitPolicyRef(ref: string): { name: string; version?: string } {
  const at = ref.lastIndexOf("@");
  return at === -1 ? { name: ref } : { name: ref.slice(0, at), version: ref.slice(at + 1) };
}

/** "tool_actions" reads as "Tool actions" when no translation names it. */
const asWords = (name: string) => {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

export function PoliciesSection() {
  const t = useTranslations("settings.policies");
  const policies = usePolicies();
  return (
    <Section title={t("title")} aside={<span className="text-xs text-muted">{t("aside")}</span>}>
      <QueryState query={policies} skeleton={<Skeleton className="h-64 rounded-none" />}>
        {(list) => (
          <ul className="divide-y divide-rule">
            {list.map((p) => {
              const { name, version } = splitPolicyRef(p.ref);
              return (
                <li key={p.ref} className="px-5 py-3.5">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-sm font-medium">
                      {isNamed(name) ? t(`names.${name}`) : asWords(name)}
                      {version ? (
                        <>
                          {" "}
                          <span className="ml-1 text-xs font-normal text-muted">{t("version", { n: version })}</span>
                        </>
                      ) : null}
                    </h3>
                    <span className="text-xs text-muted">{t("updated", { when: p.updated })}</span>
                  </div>
                  <p className="mt-1 text-sm text-grey-700">{p.summary}</p>
                </li>
              );
            })}
          </ul>
        )}
      </QueryState>
      <p className="border-t border-rule px-5 py-3 text-xs text-muted">{t("note")}</p>
    </Section>
  );
}

/** The region codes the platform runs in; their place names are in messages. */
const REGION_CODES = ["asia-south1", "asia-northeast1", "us-central1"] as const;
const isRegionCode = (code: string): code is (typeof REGION_CODES)[number] =>
  (REGION_CODES as readonly string[]).includes(code);

export function WorkspaceSection() {
  const t = useTranslations("settings.workspace");
  const { money } = useFormat();
  const org = useOrg();
  const regionValue = (code: string) => {
    // Place names come from messages for the codes the platform runs in; any other code shows as it is.
    return isRegionCode(code) ? t("regionValue", { place: t(`places.${code}`), code }) : code;
  };
  return (
    <Section title={t("title")}>
      <QueryState query={org} skeleton={<Skeleton className="h-40 rounded-none" />}>
        {(ORG) => (
          <div className="px-5 py-2">
            <KeyValues
              rows={[
                { label: t("name"), value: ORG.name },
                { label: t("cap"), value: t("capValue", { amount: money(ORG.monthlyCap) }) },
                { label: t("region"), value: regionValue(ORG.region) },
                { label: t("reviewerLocations"), value: t("reviewerLocationsValue") },
              ]}
            />
          </div>
        )}
      </QueryState>
    </Section>
  );
}
