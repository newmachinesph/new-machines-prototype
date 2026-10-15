"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { EmptyState, Id, Section } from "@/components/ui";
import { useStudioAgents } from "@/lib/queries/studio";
import { useCanBuild } from "../can-build";
import { NewAgentLink } from "./new-agent-link";

export function AgentsList() {
  const t = useTranslations("studioAgents");
  const agents = useStudioAgents();
  const canBuild = useCanBuild();
  return (
    <Section>
      <QueryState query={agents} skeleton={<Skeleton className="m-5 h-24" />}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState action={<NewAgentLink variant="secondary" />}>
              {canBuild ? t("empty") : t("emptyMember")}
            </EmptyState>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2.5 font-medium">{t("name")}</th>
                  <th className="px-3 py-2.5 font-medium">{t("model")}</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">{t("usedBy")}</th>
                  <th className="px-5 py-2.5 text-right font-medium">{t("versionHead")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {list.map((a) => (
                  <tr key={a.key}>
                    <td className="px-5 py-3">
                      <Link href={`/studio/agents/${a.key}`} className="font-medium hover:underline">
                        {a.name}
                      </Link>
                      <div className="mt-0.5 truncate text-xs text-muted">{a.summary}</div>
                    </td>
                    <td className="px-3 py-3">{a.modelProfile === "fast" ? t("fast") : t("reasoning")}</td>
                    <td className="hidden px-3 py-3 text-muted md:table-cell">
                      {a.usedBy.length ? a.usedBy.join(", ") : t("unused")}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Id>{t("version", { n: a.version })}</Id>
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
