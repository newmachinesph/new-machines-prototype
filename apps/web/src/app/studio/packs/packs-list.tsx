"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { EmptyState, Pill, Section } from "@/components/ui";
import { useStudioPacks } from "@/lib/queries/studio";
import { useCanBuild } from "../can-build";
import { NewPackLink } from "./new-pack-link";

/**
 * Under `sm` each row is a stacked card (name and version on the first line, then the steps and whether the
 * pack is in the workspace); from `sm` up the same markup is a table. The whole row opens the pack; a pack not
 * added yet links to its marketplace page, where "Review and add" lives (a team pack's slug is its key).
 */
export function PacksList() {
  const t = useTranslations("studioPacks");
  const tStudio = useTranslations("studio");
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
            <table className="block w-full text-sm sm:table">
              <thead className="hidden text-left text-xs text-muted sm:table-header-group">
                <tr>
                  <th className="px-5 py-2.5 font-medium">{t("name")}</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">{t("stepsHead")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("inWorkspace")}</th>
                  <th className="px-5 py-2.5 text-right font-medium">{t("versionHead")}</th>
                </tr>
              </thead>
              <tbody className="block divide-y divide-rule sm:table-row-group">
                {list.map((p) => (
                  <tr
                    key={p.key}
                    className="group relative grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 px-5 py-3 hover:bg-grey-50/70 sm:table-row sm:p-0"
                  >
                    <td className="min-w-0 sm:px-5 sm:py-3">
                      <Link
                        href={`/studio/packs/${p.key}`}
                        className="font-medium after:absolute after:inset-0 hover:underline"
                      >
                        {p.name}
                      </Link>
                      <div className="mt-0.5 text-xs text-muted sm:truncate">{p.outcome}</div>
                    </td>
                    <td className="col-span-2 mt-2 text-xs text-muted sm:mt-0 sm:hidden sm:px-3 sm:py-3 sm:text-sm md:table-cell">
                      {t("steps", { n: p.steps })}
                    </td>
                    <td className="col-span-2 mt-1 sm:mt-0 sm:px-3 sm:py-3">
                      {p.added ? (
                        <Pill tone="ink">{t("added")}</Pill>
                      ) : (
                        <span className="flex flex-wrap gap-x-3 text-xs text-muted sm:text-sm">
                          {t("notAdded")}
                          <Link
                            href={`/app/marketplace/${encodeURIComponent(p.key)}`}
                            className="link relative font-medium text-ink"
                          >
                            {t("addToWorkspace")}
                          </Link>
                        </span>
                      )}
                    </td>
                    <td className="tnum col-start-2 row-start-1 text-xs text-muted sm:px-5 sm:py-3 sm:text-right sm:text-sm">
                      {tStudio("version", { n: p.version })}
                      {canBuild ? (
                        <Link
                          href={`/studio/packs/new?from=${encodeURIComponent(p.key)}`}
                          aria-label={t("duplicateLabel", { name: p.name })}
                          className="link relative ml-3 font-medium text-ink"
                        >
                          {t("duplicate")}
                        </Link>
                      ) : null}
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
