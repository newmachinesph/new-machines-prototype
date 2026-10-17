"use client";

import { useTranslations } from "next-intl";
import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { PageHeader } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { usePackText } from "@/lib/content-text";
import { useAgents, usePack } from "@/lib/queries/catalog";
import { useIsLive } from "@/lib/queries/me";
import { InstallReview } from "./install-review";

export function InstallPage({ slug }: { slug: string }) {
  const t = useTranslations("marketplace.install");
  const packText = usePackText();
  const packQuery = usePack(slug);
  const agentsQuery = useAgents();
  const live = useIsLive();
  if (packQuery.error instanceof ApiError && packQuery.error.status === 404) notFound();

  return (
    <QueryState query={packQuery} skeleton={<Skeleton className="h-96" />}>
      {(p) => {
        // Settings for an added pack are live only; the demo keeps the add flow for an added pack.
        const settings = p.installed && live;
        const { name } = packText(p);
        const heading = settings ? t("settingsTitle", { name }) : t("hire", { name });
        return (
          <>
            <title>{`${heading} | New Machines`}</title>
            <PageHeader title={heading} lede={settings ? t("settingsLede") : t("lede")} />
            <QueryState query={agentsQuery} skeleton={<Skeleton className="h-96" />}>
              {() => <InstallReview pack={p} settings={settings} />}
            </QueryState>
          </>
        );
      }}
    </QueryState>
  );
}
