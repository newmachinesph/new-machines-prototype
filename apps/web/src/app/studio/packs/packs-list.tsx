"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { EmptyState, Id, Pill, Section } from "@/components/ui";
import { useStudioPacks } from "@/lib/queries/studio";
import { useCanBuild } from "../can-build";
import { NewPackLink } from "./new-pack-link";

export function PacksList() {
  const t = useTranslations("studioPacks");
  const packs = useStudioPacks();
  const canBuild = useCanBuild();
  return (
    <Section>
      <QueryState query={packs} skeleton={<Skeleton className="m-5 h-24" />}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState action={<NewPackLink variant="secondary" />}>
              {canBuild ? t("empty") : t("emptyMember")}
            </EmptyState>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2.5 font-medium">{t("name")}</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">{t("stepsHead")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("inWorkspace")}</th>
                  <th className="px-5 py-2.5 text-right font-medium">{t("versionHead")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {list.map((p) => (
                  <tr key={p.key}>
                    <td className="px-5 py-3">
                      <Link href={`/studio/packs/${p.key}`} className="font-medium hover:underline">
                        {p.name}
                      </Link>
                      <div className="mt-0.5 truncate text-xs text-muted">{p.outcome}</div>
                    </td>
                    <td className="hidden px-3 py-3 text-muted md:table-cell">{t("steps", { n: p.steps })}</td>
                    <td className="px-3 py-3">
                      {p.added ? (
                        <Pill tone="ink">{t("added")}</Pill>
                      ) : (
                        <span className="text-muted">{t("notAdded")}</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Id>{t("version", { n: p.version })}</Id>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </QueryState>
    </Section>
  );
}
