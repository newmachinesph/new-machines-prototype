"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Fragment } from "react";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { EmptyState, Section } from "@/components/ui";
import { useStudioAgents, useStudioPacks } from "@/lib/queries/studio";
import { useCanBuild } from "../can-build";
import { NewAgentLink } from "./new-agent-link";

/**
 * Under `sm` each row is a stacked card (name and version on the first line, then the model and the packs);
 * from `sm` up the same markup is a table. The whole row opens the agent; links inside it sit above that.
 */
export function AgentsList() {
  const t = useTranslations("studioAgents");
  const tStudio = useTranslations("studio");
  const agents = useStudioAgents();
  const packs = useStudioPacks();
  const canBuild = useCanBuild();
  // The list names the packs that use an agent; their keys come from the packs list. Names are unique in an org.
  const packKeys = new Map((packs.data ?? []).map((p) => [p.name, p.key]));
  return (
    <Section>
      <QueryState query={agents} skeleton={<Skeleton className="m-5 h-24" />}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState action={<NewAgentLink variant="secondary" />}>
              {canBuild ? t("empty") : t("emptyMember")}
            </EmptyState>
          ) : (
            <table className="block w-full text-sm sm:table">
              <thead className="hidden text-left text-xs text-muted sm:table-header-group">
                <tr>
                  <th className="px-5 py-2.5 font-medium">{t("name")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("model")}</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">{t("usedBy")}</th>
                  <th className="px-5 py-2.5 text-right font-medium">{t("versionHead")}</th>
                </tr>
              </thead>
              <tbody className="block divide-y divide-rule sm:table-row-group">
                {list.map((a) => (
                  <tr
                    key={a.key}
                    className="group relative grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 px-5 py-3 hover:bg-grey-50/70 sm:table-row sm:p-0"
                  >
                    <td className="min-w-0 sm:px-5 sm:py-3">
                      <Link
                        href={`/studio/agents/${a.key}`}
                        className="font-medium after:absolute after:inset-0 hover:underline"
                      >
                        {a.name}
                      </Link>
                      <div className="mt-0.5 text-xs text-muted sm:truncate">{a.summary}</div>
                    </td>
                    <td className="col-span-2 mt-2 text-xs text-muted sm:mt-0 sm:px-3 sm:py-3 sm:text-sm sm:text-ink">
                      {a.modelProfile === "fast" ? t("fast") : t("reasoning")}
                    </td>
                    <td className="col-span-2 text-xs text-muted sm:hidden sm:px-3 sm:py-3 sm:text-sm md:table-cell">
                      {a.usedBy.length ? (
                        <>
                          <span className="sm:hidden">{t("usedBy")} </span>
                          {a.usedBy.map((name, i) => {
                            const key = packKeys.get(name);
                            return (
                              <Fragment key={name}>
                                {i > 0 ? ", " : null}
                                {key ? (
                                  <Link href={`/studio/packs/${key}`} className="relative text-ink hover:underline">
                                    {name}
                                  </Link>
                                ) : (
                                  <span>{name}</span>
                                )}
                              </Fragment>
                            );
                          })}
                        </>
                      ) : (
                        t("unused")
                      )}
                    </td>
                    <td className="tnum col-start-2 row-start-1 text-xs text-muted sm:px-5 sm:py-3 sm:text-right sm:text-sm">
                      {tStudio("version", { n: a.version })}
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
