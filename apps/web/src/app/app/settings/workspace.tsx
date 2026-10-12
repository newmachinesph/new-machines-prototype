"use client";

import { useTranslations } from "next-intl";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Id, KeyValues, Section } from "@/components/ui";
import { useOrg } from "@/lib/queries/org";
import { usePolicies } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";

export function PoliciesSection() {
  const t = useTranslations("settings.policies");
  const policies = usePolicies();
  return (
    <Section title={t("title")} aside={<span className="text-xs text-muted">{t("aside")}</span>}>
      <QueryState query={policies} skeleton={<Skeleton className="h-64 rounded-none" />}>
        {(list) => (
          <ul className="divide-y divide-rule">
            {list.map((p) => (
              <li key={p.ref} className="px-5 py-3.5">
                <div className="flex items-center justify-between gap-2">
                  <Id>{p.ref}</Id>
                  <span className="text-xs text-muted">{t("updated", { when: p.updated })}</span>
                </div>
                <p className="mt-1 text-sm text-grey-700">{p.summary}</p>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      <p className="border-t border-rule px-5 py-3 text-xs text-muted">{t("note")}</p>
    </Section>
  );
}

export function WorkspaceSection() {
  const t = useTranslations("settings.workspace");
  const { money } = useFormat();
  const org = useOrg();
  return (
    <Section title={t("title")}>
      <QueryState query={org} skeleton={<Skeleton className="h-40 rounded-none" />}>
        {(ORG) => (
          <div className="px-5 py-2">
            <KeyValues
              rows={[
                { label: t("name"), value: ORG.name },
                { label: t("cap"), value: t("capValue", { amount: money(ORG.monthlyCap) }) },
                { label: t("region"), value: ORG.region },
                { label: t("reviewerLocations"), value: t("reviewerLocationsValue") },
              ]}
            />
          </div>
        )}
      </QueryState>
    </Section>
  );
}
