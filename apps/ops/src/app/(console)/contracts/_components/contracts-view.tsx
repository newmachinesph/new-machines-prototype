"use client";

import { z } from "zod";
import { type Column, DataTable } from "@/components/data-table";
import { Id, PageHeader, Section } from "@/components/ui";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { duration } from "@/lib/format";
import { definitionHref } from "../../definitions/_components/definition-logic";
import { KindState } from "../../definitions/_components/kind-state";

const minor = z.number().int().nullish().catch(null);

/** The parts of an `nm.work_contract.v1` template this page shows. Each falls back on its own. */
const contractBody = z.object({
  capability: z.string().nullish().catch(null),
  budget: z
    .object({ currency: z.string().catch("USD"), maximum_minor: minor, human_budget_minor: minor })
    .catch({ currency: "USD", maximum_minor: null, human_budget_minor: null }),
  limits: z
    .object({ max_attempts: z.number().nullish().catch(null), deadline_s: z.number().nullish().catch(null) })
    .catch({ max_attempts: null, deadline_s: null }),
  authorization: z.object({ tool_capabilities: z.array(z.string()).catch([]) }).catch({ tool_capabilities: [] }),
});

/** An amount in a contract's own currency: integer minor units and an ISO code. */
type Budget = { minor: number; currency: string };

/** Formats minor units in any ISO currency, using that currency's own number of decimals. */
export function budgetText({ minor, currency }: Budget): string {
  try {
    const format = new Intl.NumberFormat("en-US", { style: "currency", currency });
    return format.format(minor / 10 ** (format.resolvedOptions().maximumFractionDigits ?? 2));
  } catch {
    return `${minor} ${currency} (minor units)`;
  }
}

type ContractRow = {
  key: string;
  name: string;
  version: number;
  capability: string | null;
  budget: Budget | null;
  humanBudget: Budget | null;
  maxAttempts: number | null;
  deadlineS: number | null;
  capabilities: string[];
};

export function contractRow(d: DefinitionDetail): ContractRow {
  const body = contractBody.parse(d.body);
  const money = (minor: number | null | undefined): Budget | null =>
    minor == null ? null : { minor, currency: body.budget.currency };
  return {
    key: d.summary.key,
    name: d.summary.name,
    version: d.summary.version,
    capability: body.capability ?? null,
    budget: money(body.budget.maximum_minor),
    humanBudget: money(body.budget.human_budget_minor),
    maxAttempts: body.limits.max_attempts ?? null,
    deadlineS: body.limits.deadline_s ?? null,
    capabilities: body.authorization.tool_capabilities,
  };
}

const DAY = 86_400;

/** Whole days read as days ("2 days"); anything else as a duration ("1h 30m"). */
export const deadlineText = (s: number) =>
  s >= DAY && s % DAY === 0 ? `${s / DAY} ${s === DAY ? "day" : "days"}` : duration(s);

const NOT_SET = <span className="text-muted">Not set</span>;

const COLUMNS: Column<ContractRow>[] = [
  {
    key: "contract",
    header: "Contract",
    cell: (c) => (
      <span className="block min-w-0">
        <span className="block font-medium">{c.name}</span>
        {c.capability ? <Id>{c.capability}</Id> : null}
      </span>
    ),
  },
  {
    key: "budget",
    header: "Budget",
    numeric: true,
    cell: (c) =>
      c.budget ? (
        <span className="block">
          <span className="tnum">{budgetText(c.budget)}</span>
          {c.humanBudget ? (
            <span className="block text-xs text-muted">
              <span className="tnum">{budgetText(c.humanBudget)}</span> for people
            </span>
          ) : null}
        </span>
      ) : (
        NOT_SET
      ),
  },
  {
    key: "limits",
    header: "Limits",
    className: "hidden md:table-cell",
    cell: (c) =>
      c.maxAttempts == null && c.deadlineS == null ? (
        NOT_SET
      ) : (
        <span className="block">
          {c.maxAttempts != null ? <span className="block">{c.maxAttempts} attempts</span> : null}
          {c.deadlineS != null ? (
            <span className="block text-xs text-muted">Deadline {deadlineText(c.deadlineS)}</span>
          ) : null}
        </span>
      ),
  },
  {
    key: "capabilities",
    header: "Tool capabilities",
    className: "hidden lg:table-cell",
    cell: (c) => (c.capabilities.length ? c.capabilities.join(", ") : NOT_SET),
  },
  { key: "version", header: "Version", numeric: true, cell: (c) => `v${c.version}` },
];

export function ContractsView() {
  return (
    <>
      <PageHeader
        title="Work Contracts"
        lede="The terms every run of a pack is held to: the most it may spend, how many attempts and how long it gets, and the tool capabilities it is allowed. Open one to edit it."
      />
      <KindState kind="contract" what="Work contracts">
        {(details) => (
          <Section>
            <DataTable
              label="Work contracts"
              columns={COLUMNS}
              rows={details.map(contractRow)}
              rowKey={(c) => c.key}
              rowHref={(c) => definitionHref("contract", c.key)}
              empty="No work contracts yet. Create one from Definitions."
            />
          </Section>
        )}
      </KindState>
    </>
  );
}
