"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, EmptyState, Section, SimTag } from "@/components/ui";
import type { StudioListing } from "@/lib/api/gen/types.gen";
import { useStudioEarnings, useStudioListings } from "@/lib/queries/publishing";
import { listingPrices, ListingStatusPill, usePriceLabel, VersionStatusPill } from "./listing-parts";

/** "2026-09" as "September 2026" in the interface language; anything else is shown as it came. */
function monthLabel(month: string, locale: string) {
  const m = /^(\d{4})-(\d{2})/.exec(month);
  if (!m) return month;
  const at = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1));
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "long", timeZone: "UTC" }).format(at);
}

export function PublisherView() {
  const listings = useStudioListings();
  return (
    <div className="space-y-6">
      <Earnings />
      <Section>
        <QueryState query={listings} skeleton={<Skeleton className="m-5 h-24" />}>
          {(list) => (list.length === 0 ? <NothingListed /> : <ListingsTable list={list} />)}
        </QueryState>
      </Section>
      <Payouts />
    </div>
  );
}

function Earnings() {
  const t = useTranslations("studioPublisher");
  const earnings = useStudioEarnings();
  return (
    <Section>
      <QueryState query={earnings} skeleton={<Skeleton className="m-5 h-12" />}>
        {(e) => (
          <div className="px-5 py-4">
            <div className="flex items-center gap-2 text-sm text-muted">
              {t("earningsMonth")}
              <SimTag />
            </div>
            <Amount value={e.month} className="mt-1 block text-2xl font-semibold" />
            <p className="mt-1 text-xs text-muted">{t("simulated")}</p>
          </div>
        )}
      </QueryState>
    </Section>
  );
}

/** Nothing listed: where the pages to submit from are, as one line of links that reads with the sentence above. */
function NothingListed() {
  const t = useTranslations("studioPublisher");
  return (
    <EmptyState
      action={
        <p className="text-sm">
          {t.rich("goTo", {
            agents: (chunks) => (
              <Link className="link" href="/studio/agents">
                {chunks}
              </Link>
            ),
            packs: (chunks) => (
              <Link className="link" href="/studio/packs">
                {chunks}
              </Link>
            ),
          })}
        </p>
      }
    >
      {t("empty")}
    </EmptyState>
  );
}

function ListingsTable({ list }: { list: StudioListing[] }) {
  const t = useTranslations("studioPublisher");
  const price = usePriceLabel();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{t("title")}</caption>
        <thead className="text-left text-xs text-muted">
          <tr>
            <th scope="col" className="px-5 py-2.5 font-medium">
              {t("columns.name")}
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              {t("columns.kind")}
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              {t("columns.status")}
            </th>
            <th scope="col" className="px-3 py-2.5 font-medium">
              {t("columns.price")}
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              {t("columns.installs")}
            </th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">
              {t("columns.runs")}
            </th>
            <th scope="col" className="px-5 py-2.5 text-right font-medium">
              <span className="inline-flex items-center justify-end gap-1.5">
                {t("columns.earnings")}
                <SimTag />
              </span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {list.map((l) => {
            const { price: listed, inReview } = listingPrices(l);
            return (
              <tr key={l.id} className="group relative hover:bg-grey-50/70">
                <td className="px-5 py-3">
                  <Link
                    href={`/studio/publisher/${l.id}`}
                    className="font-medium after:absolute after:inset-0 hover:underline"
                  >
                    {l.name}
                  </Link>
                </td>
                <td className="px-3 py-3">{t(`kind.${l.kind}`)}</td>
                <td className="px-3 py-3">
                  <span className="flex flex-wrap gap-1.5">
                    <ListingStatusPill status={l.status} />
                    {l.latest.status !== "approved" ? <VersionStatusPill status={l.latest.status} /> : null}
                  </span>
                </td>
                <td className="tnum px-3 py-3 whitespace-nowrap">
                  {price(l.kind, listed)}
                  {inReview ? (
                    <span className="block text-xs text-muted">
                      {t("inReview", { price: price(l.kind, inReview) })}
                    </span>
                  ) : null}
                </td>
                <td className="tnum px-3 py-3 text-right">{l.installs}</td>
                <td className="tnum px-3 py-3 text-right">{l.runs30d}</td>
                <td className="px-5 py-3 text-right">
                  <Amount value={l.earningsMonth} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Payouts() {
  const t = useTranslations("studioPublisher");
  const locale = useLocale();
  const earnings = useStudioEarnings();
  return (
    <Section title={t("payouts")} aside={<SimTag />}>
      <QueryState query={earnings} skeleton={<Skeleton className="m-5 h-12" />}>
        {(e) =>
          e.payouts.length === 0 ? (
            <EmptyState>{t("noPayouts")}</EmptyState>
          ) : (
            <ul className="divide-y divide-rule">
              {[...e.payouts]
                .sort((a, b) => b.month.localeCompare(a.month))
                .map((p) => (
                  <li key={p.month} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <span>{monthLabel(p.month, locale)}</span>
                    <span className="flex items-center gap-2">
                      <Amount value={p.amount} />
                      <SimTag />
                    </span>
                  </li>
                ))}
            </ul>
          )
        }
      </QueryState>
    </Section>
  );
}
