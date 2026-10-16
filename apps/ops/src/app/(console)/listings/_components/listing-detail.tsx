"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Id, PageHeader, Pill, Section, SimTag, type Tone } from "@/components/ui";
import type { DefinitionDiff, ListingCheck, ListingVersion, OpsListingDetail } from "@/lib/api/gen/types.gen";
import { dateTime } from "@/lib/format";
import { useListing } from "@/lib/queries/listings";
import { ListingActions } from "./listing-actions";
import { historyAction, priceText, STATUS_LABEL } from "./listing-state";
import { LiveGate } from "./listings-view";

const STATUS_TONE: Record<OpsListingDetail["status"], Tone> = { pending: "human", listed: "machine", unlisted: "quiet" };
const CHECK_TONE: Record<ListingCheck["state"], Tone> = { passed: "machine", failed: "blocked", running: "human" };
const CHECK_STATE: Record<ListingCheck["state"], string> = { passed: "Passed", failed: "Failed", running: "Running" };
const CHECK_NAME: Record<ListingCheck["name"], string> = {
  definition: "Definition",
  agents: "Agents",
  sandbox: "Sandbox run",
};
const VERSION_STATUS: Record<ListingVersion["status"], string> = {
  checking: "Checking",
  checks_failed: "Checks failed",
  in_review: "In review",
  approved: "Approved",
  changes_requested: "Changes requested",
  rejected: "Rejected",
};
const CHANGE_LABEL: Record<DefinitionDiff["change"], string> = { added: "Added", changed: "Changed", removed: "Removed" };

export function ListingDetail({ listingId }: { listingId: string }) {
  return (
    <LiveGate
      demoHeader={
        <PageHeader title="Listing">
          <BackLink />
        </PageHeader>
      }
    >
      <LiveDetail listingId={listingId} />
    </LiveGate>
  );
}

function LiveDetail({ listingId }: { listingId: string }) {
  const query = useListing(listingId);
  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(listing) => <Body listing={listing} />}
    </QueryState>
  );
}

function BackLink() {
  return (
    <Link href="/listings" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" aria-hidden />
      Review queue
    </Link>
  );
}

/** The newest version by definition version, for a listing with nothing waiting. */
function latestVersion(versions: ListingVersion[]): ListingVersion | undefined {
  return versions.reduce<ListingVersion | undefined>(
    (best, v) => (!best || v.definitionVersion > best.definitionVersion ? v : best),
    undefined,
  );
}

/** The price facts: one "Price", or "Listed price" and "Price in review" when they differ. */
function priceFacts(listing: OpsListingDetail): { label: string; value: string }[] {
  const { kind, pending } = listing;
  if (listing.status === "pending") {
    // `price` is the approved version's price and is 0 until a first approval.
    const shown = pending?.price ?? latestVersion(listing.versions)?.price ?? listing.price;
    return [{ label: "Price", value: priceText(shown, kind) }];
  }
  if (pending && pending.price.amountMinor !== listing.price.amountMinor) {
    return [
      { label: "Listed price", value: priceText(listing.price, kind) },
      { label: "Price in review", value: priceText(pending.price, kind) },
    ];
  }
  return [{ label: "Price", value: priceText(listing.price, kind) }];
}

function Body({ listing }: { listing: OpsListingDetail }) {
  const pending = listing.pending;
  const inReview = pending?.status === "in_review";
  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {listing.name}
            <Pill tone={STATUS_TONE[listing.status]}>{STATUS_LABEL[listing.status]}</Pill>
          </span>
        }
        lede={`${listing.kind === "pack" ? "Pack" : "Agent"} by ${listing.publisher}`}
        actions={<ListingActions listing={{ id: listing.id, name: listing.name, kind: listing.kind, status: listing.status, inReview }} />}
      >
        <BackLink />
      </PageHeader>

      <div className="space-y-4">
        <Section title="Listing">
          <p className="flex items-center gap-2 px-5 pt-3 text-xs text-muted">
            <SimTag /> Prices are simulated: no money moves.
          </p>
          <dl className="grid gap-x-6 gap-y-2 px-5 py-4 text-sm sm:grid-cols-4">
            <Fact label="Publisher" value={listing.publisher} />
            <Fact label="Kind" value={listing.kind === "pack" ? "Pack" : "Agent"} />
            {priceFacts(listing).map((f) => (
              <Fact key={f.label} label={f.label} value={f.value} />
            ))}
            <Fact label="Key" value={<Id>{listing.key}</Id>} />
          </dl>
        </Section>

        {pending ? (
          <Section title={`Version ${pending.definitionVersion}: ${VERSION_STATUS[pending.status].toLowerCase()}`}>
            <div className="space-y-4 px-5 py-4 text-sm">
              <p className="text-muted">
                Submitted {dateTime(pending.submittedAt)} by {pending.submittedBy}. Price: {priceText(pending.price, listing.kind)}.
              </p>
              {pending.status === "checking" || pending.status === "checks_failed" ? (
                <p className="font-medium">Reviewable once checks pass</p>
              ) : null}
              <Checks checks={pending.checks} />
              <Diffs diff={listing.diff} />
            </div>
          </Section>
        ) : (
          <p className="text-sm text-muted">No version is waiting for review.</p>
        )}

        <Section title="Versions">
          <DataTable
            label="Versions of this listing"
            columns={versionColumns(listing.kind)}
            rows={listing.versions}
            rowKey={(v) => v.id}
            empty="No versions yet."
            maxHeight="max-h-80"
          />
        </Section>

        <Section title="History">
          {listing.history.length === 0 ? (
            <p className="px-5 py-4 text-sm text-muted">Nothing has happened to this listing yet.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {listing.history.map((h, i) => (
                <li key={`${i}-${h.at}-${h.action}`} className="px-5 py-3 text-sm">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium">{historyAction(h.action)}</span>
                    <span>{h.by}</span>
                    <span className="text-xs text-muted">{dateTime(h.at)}</span>
                  </div>
                  {h.note ? <p className="mt-0.5 text-grey-700">{h.note}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </>
  );
}

const versionColumns = (kind: OpsListingDetail["kind"]): Column<ListingVersion>[] => [
  { key: "version", header: "Version", cell: (v) => `v${v.definitionVersion}` },
  {
    key: "status",
    header: "Status",
    cell: (v) => (
      <span className="block">
        {VERSION_STATUS[v.status]}
        {v.note ? <span className="block text-xs text-muted md:hidden">{v.note}</span> : null}
      </span>
    ),
  },
  { key: "price", header: "Price", numeric: true, cell: (v) => priceText(v.price, kind) },
  { key: "submitted", header: "Submitted", cell: (v) => `${dateTime(v.submittedAt)} by ${v.submittedBy}` },
  {
    key: "decided",
    header: "Decision",
    className: "hidden md:table-cell",
    cell: (v) =>
      v.decidedAt ? (
        <span className="block">
          {dateTime(v.decidedAt)}
          {v.decidedBy ? ` by ${v.decidedBy}` : ""}
          {v.note ? <span className="block text-xs text-muted">{v.note}</span> : null}
        </span>
      ) : (
        <span className="text-muted">Not decided</span>
      ),
  },
];

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function Checks({ checks }: { checks: ListingCheck[] }) {
  if (checks.length === 0) return <p className="text-muted">No checks have run yet.</p>;
  return (
    <div>
      <h3 className="mb-1 font-medium">Checks</h3>
      <ul className="divide-y divide-rule">
        {checks.map((c) => (
          <li key={c.name} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
            <span className="w-28 shrink-0 font-medium">{CHECK_NAME[c.name]}</span>
            <Pill tone={CHECK_TONE[c.state]}>{CHECK_STATE[c.state]}</Pill>
            <span className="min-w-0 flex-1 text-grey-700">{c.detail}</span>
            {c.runId ? (
              <Link href={`/runs/${c.runId}`} className="text-sm underline underline-offset-2">
                View sandbox run
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Diffs({ diff }: { diff: DefinitionDiff[] }) {
  return (
    <div>
      <h3 className="mb-1 font-medium">Changes from the approved version</h3>
      {diff.length === 0 ? (
        <p className="text-muted">First version: nothing to compare.</p>
      ) : (
        <div className="space-y-2">
          {diff.map((d) => (
            <details key={`${d.kind}/${d.key}/${d.path}`} open className="rounded-md border border-rule">
              <summary className="cursor-pointer px-3 py-2">
                <span className="font-medium">{d.key}</span> <span className="text-muted">{d.kind}</span>{" "}
                <Id>{d.path}</Id> <Pill tone="quiet">{CHANGE_LABEL[d.change]}</Pill>
              </summary>
              <pre className="overflow-x-auto border-t border-rule bg-grey-100 px-3 py-2 text-xs leading-relaxed">
                {d.unified}
              </pre>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
