import { Stat } from "@/components/stat";
import type { OpsOverview } from "@/lib/api/gen/types.gen";
import { count, money } from "@/lib/format";

/**
 * Developer publishing figures for the overview: listings waiting for review and this month's publisher
 * earnings. Renders nothing when the overview carries neither (the demo workspace). Earnings are always
 * simulated money, so they always carry the Simulated tag.
 */
export function PublishingStats({ overview }: { overview: OpsOverview }) {
  const { listingsInReview, publisherEarningsMonth } = overview;
  if (listingsInReview === undefined && publisherEarningsMonth === undefined) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
      {listingsInReview !== undefined ? (
        <Stat
          label="Listings in review"
          value={count(listingsInReview)}
          sub="Waiting for an operator decision"
          tone={listingsInReview > 0 ? "human" : "default"}
          href="/listings"
        />
      ) : null}
      {publisherEarningsMonth !== undefined ? (
        <Stat
          label="Publisher earnings this month"
          value={money(publisherEarningsMonth)}
          sub="Simulated: no money moves"
          simulated
        />
      ) : null}
    </div>
  );
}
