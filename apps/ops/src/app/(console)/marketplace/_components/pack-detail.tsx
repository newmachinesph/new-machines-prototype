"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { LiveSampleNote } from "@/components/live-sample-note";
import { Amount, Callout, Id, KeyValues, PageHeader, Pill, Section, type Tone } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { PackConnector, PackListingDetail } from "@/lib/api/gen/types.gen";
import { count, date, dateTime, pct } from "@/lib/format";
import { usePack } from "@/lib/queries/marketplace";
import { PackActions } from "./pack-actions";
import { STATUS_LABEL } from "./pack-state";

const STATUS_TONE: Record<PackListingDetail["status"], Tone> = {
  draft: "quiet",
  in_review: "human",
  published: "machine",
  deprecated: "quiet",
  rejected: "blocked",
};

const ACCESS: Record<PackConnector["access"], { label: string; tone: Tone }> = {
  read: { label: "Read", tone: "quiet" },
  "write (approval)": { label: "Write, needs approval", tone: "policy" },
  write: { label: "Write", tone: "human" },
};

const CONNECTOR_COLUMNS: Column<PackConnector>[] = [
  { key: "app", header: "App", cell: (c) => <span className="font-medium">{c.app}</span> },
  {
    key: "access",
    header: "Access",
    cell: (c) => <Pill tone={ACCESS[c.access].tone}>{ACCESS[c.access].label}</Pill>,
  },
  { key: "mocked", header: "Mode", cell: (c) => (c.mocked ? "Sandbox mock" : "Live") },
];

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function PackDetail({ slug }: { slug: string }) {
  const query = usePack(slug);
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  if (notFound) {
    return (
      <>
        <BackLink />
        <Section className="p-6">
          <h1 className="h-page">No pack with the slug {slug}</h1>
          <p className="mt-2 max-w-[60ch] text-sm text-muted">
            It may have been renamed or never created. Go back to the marketplace and pick it from a tab.
          </p>
        </Section>
      </>
    );
  }

  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(pack) => <PackBody pack={pack} />}
    </QueryState>
  );
}

function BackLink() {
  return (
    <Link href="/marketplace" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" aria-hidden />
      Marketplace
    </Link>
  );
}

function PackBody({ pack }: { pack: PackListingDetail }) {
  const p = pack.pack;
  const passport = p.passport;

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {pack.name}
            <span className="flex items-center gap-1.5 align-middle">
              <Pill tone={STATUS_TONE[pack.status]}>{STATUS_LABEL[pack.status]}</Pill>
              {pack.certified ? <Pill tone="ink">Certified</Pill> : null}
            </span>
          </span>
        }
        lede={p.outcome}
        actions={<PackActions pack={pack} />}
        below={<LiveSampleNote>This pack listing is sample data, not the live catalog.</LiveSampleNote>}
      >
        <BackLink />
      </PageHeader>

      {pack.reviewNotes ? (
        <div className="mb-4">
          <Callout tone={pack.status === "rejected" ? "blocked" : "info"} title="Review notes">
            {pack.reviewNotes}
          </Callout>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4">
          <Section title="About this pack">
            <div className="space-y-3 px-5 py-4 text-sm leading-relaxed">
              <p>{p.description}</p>
              <p>
                <span className="font-medium">Human review. </span>
                {p.humanReview}
              </p>
            </div>
          </Section>

          <Section title="Connectors and access">
            <DataTable
              label="Connectors this pack uses"
              columns={CONNECTOR_COLUMNS}
              rows={p.connectors}
              rowKey={(c) => c.app}
              empty="This pack uses no connectors."
              maxHeight="max-h-80"
            />
          </Section>

          <Section title="Trust passport">
            {passport ? (
              <div className="space-y-4 px-5 py-4 text-sm">
                <p className="text-muted">
                  Tested {date(passport.testedOn)} by {passport.testedBy} on {passport.cohort}. Sample of{" "}
                  <span className="tnum">{count(passport.sampleSize)}</span> cases.
                </p>
                <dl className="divide-y divide-rule">
                  {passport.results.map((r) => (
                    <div key={r.label} className="flex items-baseline justify-between gap-4 py-2">
                      <dt>
                        {r.label}
                        {r.note ? <span className="block text-xs text-muted">{r.note}</span> : null}
                      </dt>
                      <dd className="tnum shrink-0 font-medium">{count(r.value)}</dd>
                    </div>
                  ))}
                </dl>
                <PassportList title="Limitations" items={passport.limitations} />
                <PassportList title="Retest triggers" items={passport.retestTriggers} />
              </div>
            ) : (
              <p className="px-5 py-4 text-sm text-muted">
                No passport on file. Ask the publisher to run the evaluation before this pack is approved.
              </p>
            )}
          </Section>
        </div>

        <div className="space-y-4">
          <Section title="Listing">
            <KeyValues
              className="px-5"
              rows={[
                { label: "Slug", value: <Id>{pack.slug}</Id> },
                { label: "Version", value: pack.version },
                { label: "Publisher", value: pack.publisher },
                { label: "Category", value: pack.category },
                { label: "Function", value: pack.function?.name ?? "Not classified" },
                {
                  label: "Industries",
                  value: pack.industries?.length ? pack.industries.map((i) => i.name).join(", ") : "None set",
                },
                { label: "Risk class", value: sentence(pack.riskClass) },
                { label: "Price", value: pack.priceNote },
                { label: "Regions", value: p.regions.join(", ") || "None set" },
                { label: "Installs", value: <span className="tnum">{count(pack.installs)}</span> },
                { label: "Runs (30d)", value: <span className="tnum">{count(pack.runs30d)}</span> },
                {
                  label: "Success rate",
                  value: <span className="tnum">{pack.runs30d > 0 ? pct(pack.successRate) : "None yet"}</span>,
                },
                { label: "Updated", value: dateTime(pack.updatedAt) },
                ...(pack.submittedAt ? [{ label: "Submitted", value: dateTime(pack.submittedAt) }] : []),
              ]}
            />
          </Section>

          <Section title="Estimate per run">
            <KeyValues
              className="px-5"
              rows={[
                {
                  label: "AI cost",
                  value: (
                    <>
                      <Amount value={p.estimate.aiMin} /> to <Amount value={p.estimate.aiMax} />
                    </>
                  ),
                },
                { label: "Human review, at most", value: <Amount value={p.estimate.humanMax} /> },
              ]}
            />
          </Section>

          <Section title="History">
            {pack.history.length ? (
              <ol className="divide-y divide-rule">
                {pack.history.map((h, i) => (
                  <li key={`${h.at}-${i}`} className="px-5 py-3 text-sm">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium">{h.action}</span>
                      <time dateTime={h.at} className="tnum shrink-0 text-xs text-muted">
                        {dateTime(h.at)}
                      </time>
                    </div>
                    <div className="text-xs text-muted">{h.by}</div>
                    {h.note ? <p className="mt-1 text-grey-700">{h.note}</p> : null}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="px-5 py-4 text-sm text-muted">No history yet.</p>
            )}
          </Section>
        </div>
      </div>
    </>
  );
}

function PassportList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-grey-700">
        {items.map((it) => (
          <li key={it}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
