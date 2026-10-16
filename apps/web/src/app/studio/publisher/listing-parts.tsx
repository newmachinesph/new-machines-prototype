"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Pill } from "@/components/ui";
import type { ListingCheck, ListingVersion, Money, StudioListing } from "@/lib/api/gen/types.gen";
import { useRun } from "@/lib/queries/runs";
import { useFormat } from "@/lib/use-format";

type ListingStatus = StudioListing["status"];
type VersionStatus = ListingVersion["status"];

const LISTING_TONE = { pending: "human", listed: "ink", unlisted: "quiet" } as const;
const VERSION_TONE = {
  checking: "machine",
  checks_failed: "blocked",
  in_review: "human",
  approved: "ink",
  changes_requested: "human",
  rejected: "blocked",
} as const;
/** Versions still on their way to a decision: checked, then reviewed. */
const OPEN: VersionStatus[] = ["checking", "in_review"];

export function ListingStatusPill({ status }: { status: ListingStatus }) {
  const t = useTranslations("studioPublisher.status");
  return <Pill tone={LISTING_TONE[status]}>{t(status)}</Pill>;
}

export function VersionStatusPill({ status }: { status: VersionStatus }) {
  const t = useTranslations("studioPublisher.version");
  return <Pill tone={VERSION_TONE[status]}>{t(status)}</Pill>;
}

/** "{price} per run" for a pack, "per call" for an agent, "No fee" when the price is zero. */
export function usePriceLabel() {
  const t = useTranslations("studioPublisher");
  const { money } = useFormat();
  return (kind: StudioListing["kind"], price: Money) =>
    price.amountMinor === 0 ? t("noFee") : t(kind === "pack" ? "perRun" : "perCall", { price: money(price) });
}

/**
 * The prices to show for a listing. `listing.price` is the approved version's and is 0 until a version is first
 * approved, so before that the newest version's price is the price. Once listed, a version still on its way to a
 * decision at another price is shown beside it as `inReview`.
 */
export function listingPrices(l: StudioListing): { price: Money; inReview?: Money } {
  if (l.approvedVersion == null) return { price: l.latest.price };
  const open = OPEN.includes(l.latest.status) && l.latest.price.amountMinor !== l.price.amountMinor;
  return open ? { price: l.price, inReview: l.latest.price } : { price: l.price };
}

/** The API's fixed words for a passed or running check, by check and state, in the interface language. */
const CHECK_DETAIL: Record<string, "definition" | "agents" | "sandboxRunning" | "sandboxPassed"> = {
  "definition:passed": "definition",
  "agents:passed": "agents",
  "sandbox:running": "sandboxRunning",
  "sandbox:passed": "sandboxPassed",
};

/** A check's detail: the interface language's words for a fixed one, the API's own for a failure. */
export function useCheckDetail() {
  const t = useTranslations("studioPublisher.checkDetail");
  return (c: ListingCheck) => {
    const key = CHECK_DETAIL[`${c.name}:${c.state}`];
    return key ? t(key) : c.detail;
  };
}

/**
 * While a version is `checking`, says so when its sandbox check run waits for a person: the reviewer task is in
 * the publisher's own workspace, so nothing else tells them. Links to the run unless the page already does.
 */
export function CheckWaitingNote({ version, link = true }: { version: ListingVersion; link?: boolean }) {
  const runId = version.status === "checking" ? version.checks.find((c) => c.name === "sandbox")?.runId : undefined;
  // Mounted only for a checking version, so a settled one never reads its run.
  return runId ? <WaitingForReviewer runId={runId} link={link} /> : null;
}

function WaitingForReviewer({ runId, link }: { runId: string; link: boolean }) {
  const t = useTranslations("studioPublisher");
  const run = useRun(runId);
  if (run.data?.status !== "WAITING_FOR_HUMAN") return null;
  return (
    <p className="text-sm text-muted">
      {t("checkWaiting")}{" "}
      {link ? (
        <Link href={`/app/runs/${runId}`} className="link">
          {t("checkWaitingLink")}
        </Link>
      ) : null}
    </p>
  );
}
