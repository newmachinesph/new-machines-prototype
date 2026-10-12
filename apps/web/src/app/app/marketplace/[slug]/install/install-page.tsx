"use client";

import { useTranslations } from "next-intl";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { useAgents, usePack } from "@/lib/queries/catalog";
import { InstallReview } from "./install-review";

export function InstallPage({ slug }: { slug: string }) {
  const t = useTranslations("marketplace.install");
  const packQuery = usePack(slug);
  const agentsQuery = useAgents();
  if (packQuery.error instanceof ApiError && packQuery.error.status === 404) notFound();

  return (
    <QueryState query={packQuery} skeleton={<Skeleton className="h-96" />}>
      {(p) => (
        <>
          <title>{`${t("hire", { name: p.name })} | New Machines`}</title>
          <PageHeader title={t("hire", { name: p.name })} lede={t("lede")} />
          <QueryState query={agentsQuery} skeleton={<Skeleton className="h-96" />}>
            {() => <InstallReview pack={p} />}
          </QueryState>
        </>
      )}
    </QueryState>
  );
}
