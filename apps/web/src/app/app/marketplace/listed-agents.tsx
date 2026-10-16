"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { ActorGlyph, ButtonLink } from "@/components/ui";
import { useFeeLabel } from "@/lib/listing-fee";
import { useCanBuild } from "@/app/studio/can-build";
import type { Agent } from "@/lib/types";

/** The agents other publishers have listed: who made each, what it costs per call, and where to use it. */
export function ListedAgents({ agents }: { agents: Agent[] }) {
  const t = useTranslations("listedMarket");
  const fee = useFeeLabel();
  const canBuild = useCanBuild();
  if (agents.length === 0) {
    return <p className="panel px-5 py-10 text-center text-sm text-muted">{t("agentsEmpty")}</p>;
  }
  return (
    <ul className="grid [grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-4">
      {agents.map((a) => (
        <li key={a.id} className="panel flex h-full flex-col p-5">
          <div className="flex items-start gap-2">
            <ActorGlyph actor="machine" className="mt-1.5 size-2.5" />
            <div className="min-w-0 flex-1">
              <Link
                href={`/app/agents/${encodeURIComponent(a.id)}`}
                className="text-[15px] font-semibold hover:underline"
              >
                {a.name}
              </Link>
              {a.listing ? (
                <div className="mt-0.5 text-xs text-muted">{t("by", { publisher: a.listing.publisher })}</div>
              ) : null}
            </div>
            {a.listing ? <span className="tnum shrink-0 text-xs text-grey-700">{fee(a.listing)}</span> : null}
          </div>
          <p className="mt-3 text-sm leading-relaxed text-grey-700">{a.summary}</p>
          {/* Only owners and admins build in the Studio. */}
          {canBuild ? (
            <div className="mt-auto pt-4">
              <ButtonLink href="/studio/packs" variant="secondary" className="h-8">
                {t("useInStudio")}
              </ButtonLink>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
