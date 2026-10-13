"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { z } from "zod";
import { type Column, DataTable } from "@/components/data-table";
import { ReadOnly } from "@/components/read-only";
import { Button, ButtonLink, Id, PageHeader, Pill, Section } from "@/components/ui";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { useCanWrite } from "@/lib/queries/ops";
import { definitionHref } from "../../definitions/_components/definition-logic";
import { KindState } from "../../definitions/_components/kind-state";

/** The parts of an `nm.agent.manifest.v1.1` body this page shows; anything else in the body is ignored. */
const agentBody = z.object({
  capabilities: z.array(z.string()).catch([]),
  runtime: z
    .object({
      model_profile: z.string().nullish().catch(null),
      tools: z.array(z.string()).catch([]),
      skills: z.array(z.string()).catch([]),
      max_turns: z.number().nullish().catch(null),
    })
    .catch({ model_profile: null, tools: [], skills: [], max_turns: null }),
});

type AgentRow = {
  key: string;
  name: string;
  version: number;
  modelProfile: string | null;
  tools: string[];
  skills: string[];
  maxTurns: number | null;
  capabilities: string[];
  /** Keys of the packs whose `agents` list names this agent. */
  packs: string[];
};

/** `skills/match-orders.md` → `match-orders`. */
const skillName = (path: string) => path.replace(/^.*\//, "").replace(/\.md$/, "");

export function agentRow(d: DefinitionDetail): AgentRow {
  // Every field falls back on its own, so a hand-edited body never breaks the page.
  const body = agentBody.parse(d.body);
  return {
    key: d.summary.key,
    name: d.summary.name,
    version: d.summary.version,
    modelProfile: body.runtime.model_profile ?? null,
    tools: body.runtime.tools,
    skills: body.runtime.skills.map(skillName),
    maxTurns: body.runtime.max_turns ?? null,
    capabilities: body.capabilities,
    packs: d.usedBy.filter((r) => r.kind === "pack").map((r) => r.key),
  };
}

const list = (items: string[]) => (items.length ? items.join(", ") : <span className="text-muted">None</span>);

const COLUMNS: Column<AgentRow>[] = [
  {
    key: "agent",
    header: "Agent",
    cell: (a) => (
      <span className="block min-w-0">
        <span className="block font-medium">{a.name}</span>
        {a.capabilities.length ? <Id>{a.capabilities.join(", ")}</Id> : null}
      </span>
    ),
  },
  {
    key: "model",
    header: "Model profile",
    cell: (a) =>
      a.modelProfile ? <Pill tone="machine">{a.modelProfile}</Pill> : <span className="text-muted">None</span>,
  },
  { key: "tools", header: "Tools", className: "hidden md:table-cell", cell: (a) => list(a.tools) },
  { key: "skills", header: "Skills", className: "hidden md:table-cell", cell: (a) => list(a.skills) },
  {
    key: "usedBy",
    header: "Used by",
    cell: (a) =>
      a.packs.length ? (
        <span className="flex flex-wrap gap-x-3 gap-y-1">
          {a.packs.map((key) => (
            <Link key={key} href={definitionHref("pack", key)} className="font-mono text-[12px] hover:underline">
              {key}
            </Link>
          ))}
        </span>
      ) : (
        <span className="text-muted">No pack</span>
      ),
  },
  {
    key: "turns",
    header: "Max turns",
    numeric: true,
    className: "hidden lg:table-cell",
    cell: (a) => a.maxTurns ?? "Not set",
  },
  { key: "version", header: "Version", numeric: true, cell: (a) => `v${a.version}` },
];

/** The definitions page's new-definition dialog, opened with the agent kind chosen. */
const NEW_AGENT_HREF = "/definitions?kind=agent&action=new";

function NewAgent() {
  const canWrite = useCanWrite();
  const label = (
    <>
      <Plus className="size-4" aria-hidden />
      New agent
    </>
  );
  return canWrite ? (
    <ButtonLink href={NEW_AGENT_HREF}>{label}</ButtonLink>
  ) : (
    <ReadOnly>
      <Button disabled>{label}</Button>
    </ReadOnly>
  );
}

export function AgentsView() {
  return (
    <>
      <PageHeader
        title="Agents"
        lede="The base agents packs are built from: the model profile each one runs on, the tools it may call, the skills it reads and the packs that use it. Open one to edit it."
        actions={<NewAgent />}
      />
      <KindState kind="agent" what="Agents">
        {(details) => (
          <Section>
            <DataTable
              label="Agents"
              columns={COLUMNS}
              rows={details.map(agentRow)}
              rowKey={(a) => a.key}
              rowHref={(a) => definitionHref("agent", a.key)}
              empty="No agents yet. Create one from Definitions."
            />
          </Section>
        )}
      </KindState>
    </>
  );
}
