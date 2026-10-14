"use client";

import { parseAsStringLiteral, useQueryState } from "nuqs";
import { Segmented } from "@/components/base";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Amount, Pill, Section } from "@/components/ui";
import type { Reviewer } from "@/lib/api/gen/types.gen";
import { count, date, pct } from "@/lib/format";
import { useOpsWorkspace } from "@/lib/queries/ops";
import { useReviewers } from "@/lib/queries/workforce";
import { ReviewerActions } from "./reviewer-actions";
import { TABS, TAB_STATUS, type Tab, capitalize, countByTab, resolveTab, tabsFor } from "./tabs";

const LEVEL_TONE = { trainee: "quiet", qualified: "machine", senior: "ink" } as const;

const EMPTY: Record<Tab, string> = {
  applicants: "No applicants waiting. New applications appear here as people sign up to review.",
  active: "No active reviewers. Approve an applicant to start building the pool.",
  suspended: "Nobody is suspended.",
};

/** The live network has no applicants, so its empty states never mention approving one. */
const LIVE_EMPTY: Record<Tab, string> = {
  ...EMPTY,
  active: "No network reviewers yet. People join when they turn on Review for the network in the reviewer portal.",
};

const person: Column<Reviewer> = {
  key: "name",
  header: "Reviewer",
  cell: (r) => (
    <div className="min-w-0">
      <div className="font-medium">{r.name}</div>
      <div className="truncate text-xs text-muted">{r.country ? `${r.email} · ${r.country}` : r.email}</div>
    </div>
  ),
};
const skills: Column<Reviewer> = {
  key: "skills",
  header: "Skills",
  className: "hidden xl:table-cell",
  cell: (r) => {
    const text = r.skills.join(", ") || "None listed";
    return (
      <span className="block max-w-40 truncate text-grey-700" title={text}>
        {text}
      </span>
    );
  },
};
const actions: Column<Reviewer> = {
  key: "actions",
  header: <span className="sr-only">Actions</span>,
  className: "sticky right-0 z-[1] bg-paper text-right",
  cell: (r) => <ReviewerActions reviewer={r} />,
};
const level: Column<Reviewer> = {
  key: "level",
  header: "Level",
  cell: (r) => <Pill tone={LEVEL_TONE[r.level]}>{capitalize(r.level)}</Pill>,
};

const APPLICANT_COLUMNS: Column<Reviewer>[] = [
  person,
  { key: "langs", header: "Languages", className: "hidden md:table-cell", cell: (r) => r.languages.join(", ") },
  skills,
  { key: "applied", header: "Applied", cell: (r) => date(r.joinedAt) },
  actions,
];

const MEMBER_COLUMNS: Column<Reviewer>[] = [
  person,
  level,
  skills,
  { key: "tasks", header: "Tasks (30d)", numeric: true, cell: (r) => count(r.tasksDone30d) },
  { key: "acc", header: "Accuracy", numeric: true, cell: (r) => pct(r.accuracy) },
  {
    key: "median",
    header: "Median min",
    numeric: true,
    className: "hidden 2xl:table-cell",
    cell: (r) => r.medianMinutes,
  },
  {
    key: "earn",
    header: "Earnings (30d)",
    numeric: true,
    className: "hidden md:table-cell",
    cell: (r) => <Amount value={r.earnings30d} />,
  },
  { key: "queue", header: "Queue", numeric: true, className: "hidden 2xl:table-cell", cell: (r) => count(r.queue) },
  actions,
];

/** The live network has no levels or accuracy yet; its earnings are simulated. */
const LIVE_COLUMNS: Column<Reviewer>[] = [
  person,
  { key: "langs", header: "Languages", className: "hidden md:table-cell", cell: (r) => r.languages.join(", ") },
  skills,
  { key: "tasks", header: "Network tasks (30d)", numeric: true, cell: (r) => count(r.tasksDone30d) },
  {
    key: "median",
    header: "Median min",
    numeric: true,
    className: "hidden 2xl:table-cell",
    cell: (r) => r.medianMinutes,
  },
  {
    key: "earn",
    header: "Simulated earnings (30d)",
    numeric: true,
    className: "hidden md:table-cell",
    cell: (r) => <Amount value={r.earnings30d} />,
  },
  { key: "queue", header: "Queue", numeric: true, className: "hidden 2xl:table-cell", cell: (r) => count(r.queue) },
  actions,
];

/** The page lede. The live workspace lists the New Machines reviewer network. */
export function WorkforceLede() {
  return useOpsWorkspace() === "live"
    ? "Network reviewers who chose to review for New Machines from the reviewer portal. Suspend anyone who should stop receiving network tasks."
    : "Human reviewers who take on tasks when a run needs a person. Approve applicants, set levels, and pause anyone who should stop receiving work.";
}

export function WorkforceView() {
  const query = useReviewers();
  const live = useOpsWorkspace() === "live";
  const [requested, setTab] = useQueryState("tab", parseAsStringLiteral(TABS));

  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(reviewers) => {
        const counts = countByTab(reviewers);
        const tab = resolveTab(requested, counts, live);
        const rows = reviewers.filter((r) => r.status === TAB_STATUS[tab]);
        const columns = live ? LIVE_COLUMNS : tab === "applicants" ? APPLICANT_COLUMNS : MEMBER_COLUMNS;
        return (
          <div className="space-y-4">
            <div className="flex">
              <Segmented
                label="Reviewer status"
                value={tab}
                onValueChange={(t) => void setTab(t)}
                options={tabsFor(live).map((t) => ({ value: t, label: capitalize(t), count: counts[t] }))}
              />
            </div>
            <Section>
              <DataTable
                label={`${capitalize(tab)} reviewers`}
                columns={columns}
                rows={rows}
                rowKey={(r) => r.id}
                empty={(live ? LIVE_EMPTY : EMPTY)[tab]}
                maxHeight="max-h-[70vh]"
              />
            </Section>
          </div>
        );
      }}
    </QueryState>
  );
}
