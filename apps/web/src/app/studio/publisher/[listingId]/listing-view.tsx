"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, Callout, KeyValues, PageHeader, Pill, Section, SimTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { ListingCheck, ListingVersion, StudioListingDetail } from "@/lib/api/gen/types.gen";
import { useStudioListing } from "@/lib/queries/publishing";
import { useFormat } from "@/lib/use-format";
import {
  CheckWaitingNote,
  listingPrices,
  ListingStatusPill,
  useCheckDetail,
  usePriceLabel,
  VersionStatusPill,
} from "../listing-parts";

const NOTE_TONE: Partial<Record<ListingVersion["status"], "warn" | "blocked" | "info">> = {
  changes_requested: "warn",
  rejected: "blocked",
  approved: "info",
};
const CHECK_TONE = { passed: "ink", failed: "blocked", running: "machine" } as const;

function BackLink() {
  const t = useTranslations("studioPublisher");
  return (
    <Link href="/studio/publisher" className="mb-2 inline-block text-sm text-muted hover:underline">
      {t("back")}
    </Link>
  );
}

/** Another workspace's listing, or a mistyped id: said in place, with the way back. */
function NotFound() {
  const t = useTranslations("studioPublisher");
  return (
    <PageHeader title={t("notFoundTitle")} lede={t("notFoundBody")}>
      <BackLink />
    </PageHeader>
  );
}

/** One price row, or the listed price and the different price of the version in review. */
function usePriceRows(l: StudioListingDetail) {
  const t = useTranslations("studioPublisher");
  const price = usePriceLabel();
  const { price: listed, inReview } = listingPrices(l);
  if (!inReview) return [{ label: t("columns.price"), value: price(l.kind, listed) }];
  return [
    { label: t("listedPrice"), value: price(l.kind, listed) },
    { label: t("priceInReview"), value: price(l.kind, inReview) },
  ];
}

export function ListingView({ listingId }: { listingId: string }) {
  const listing = useStudioListing(listingId);
  if (listing.error instanceof ApiError && listing.error.status === 404 && listing.data === undefined) {
    return <NotFound />;
  }
  return (
    <QueryState query={listing} skeleton={<Skeleton className="h-40" />}>
      {(l) => <Listing listing={l} />}
    </QueryState>
  );
}

function Listing({ listing: l }: { listing: StudioListingDetail }) {
  const t = useTranslations("studioPublisher");
  const priceRows = usePriceRows(l);
  return (
    <div className="space-y-6">
      <PageHeader title={l.name} lede={t(`kind.${l.kind}`)}>
        <BackLink />
      </PageHeader>
      <Section>
        <KeyValues
          className="px-5 py-4"
          rows={[
            { label: t("columns.status"), value: <ListingStatusPill status={l.status} /> },
            ...priceRows,
            { label: t("columns.installs"), value: <span className="tnum">{l.installs}</span> },
            { label: t("columns.runs"), value: <span className="tnum">{l.runs30d}</span> },
            {
              label: t("columns.earnings"),
              value: (
                <span className="flex items-center gap-2">
                  <Amount value={l.earningsMonth} />
                  <SimTag />
                </span>
              ),
            },
          ]}
        />
      </Section>
      <Section title={t("versions")}>
        <ul className="divide-y divide-rule">
          {[...l.versions]
            .sort((a, b) => b.definitionVersion - a.definitionVersion)
            .map((v) => (
              <VersionRow key={v.id} version={v} kind={l.kind} />
            ))}
        </ul>
      </Section>
    </div>
  );
}

function VersionRow({ version: v, kind }: { version: ListingVersion; kind: "agent" | "pack" }) {
  const t = useTranslations("studioPublisher");
  const { dateTime } = useFormat();
  const price = usePriceLabel();
  const tone = NOTE_TONE[v.status];
  return (
    <li className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{t("versionLabel", { n: v.definitionVersion })}</h3>
        <VersionStatusPill status={v.status} />
        <span className="tnum text-sm text-muted">{price(kind, v.price)}</span>
      </div>
      <p className="text-xs text-muted">{t("submittedBy", { by: v.submittedBy, at: dateTime(v.submittedAt) })}</p>
      {v.checks.length > 0 ? (
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-muted">{t("checks")}</h4>
          <ul className="space-y-2">
            {v.checks.map((c) => (
              <CheckRow key={c.name} check={c} />
            ))}
          </ul>
        </div>
      ) : null}
      <CheckWaitingNote version={v} />
      {v.note && tone ? (
        <Callout tone={tone} title={t("note")} announce={false}>
          {v.note}
        </Callout>
      ) : null}
    </li>
  );
}

function CheckRow({ check: c }: { check: ListingCheck }) {
  const t = useTranslations("studioPublisher");
  const detail = useCheckDetail();
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className="font-medium">{t(`check.${c.name}`)}</span>
      <Pill tone={CHECK_TONE[c.state]}>{t(`checkState.${c.state}`)}</Pill>
      <span className="text-muted">{detail(c)}</span>
      {c.runId ? (
        <Link href={`/app/runs/${c.runId}`} className="font-medium hover:underline">
          {t("openRun")}
        </Link>
      ) : null}
    </li>
  );
}
