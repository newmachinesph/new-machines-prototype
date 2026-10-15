/**
 * What the palette offers: every kind of step, then the registry's agents, app tools and memory spaces
 * (getStudioPalette), each as the step it adds. Pure: no React.
 */
import type { Palette } from "@/lib/api/gen/types.gen";
import type { NewStep } from "./graph";
import { isBlockedTool, isReadTool } from "./rules";

export type AddKind =
  | "memory"
  | "agent"
  | "connector"
  | "decision"
  | "human_workforce"
  | "approval"
  | "verification"
  | "endCompleted"
  | "endFailed";

const DAY_S = 86_400;

/**
 * A new step of each kind. Settings that need a choice start empty, so the step shows what is missing: a blank
 * decision has no rules yet (the settings panel adds them), and an app step starts with no arguments, so the tool's
 * required ones are reported as missing until they are filled in.
 */
export const BLANK_STEPS: Record<AddKind, NewStep> = {
  memory: { type: "memory", config: { op: "recall" } },
  agent: { type: "agent", config: { inputs: {} } },
  connector: { type: "connector", config: { args: {} } },
  decision: { type: "decision", config: {} },
  human_workforce: { type: "human_workforce", config: { timeout_s: DAY_S } },
  approval: { type: "approval", config: { timeout_s: DAY_S } },
  verification: { type: "verification", config: { checks: [] } },
  endCompleted: { type: "end", config: { status: "COMPLETED" } },
  endFailed: { type: "end", config: { status: "FAILED" } },
};
export const ADD_KINDS = Object.keys(BLANK_STEPS) as AddKind[];

export type PaletteEntry =
  | { kind: "step"; key: string; add: AddKind; step: NewStep }
  | { kind: "agent"; key: string; title: string; summary: string; team: boolean; step: NewStep }
  | { kind: "tool"; key: string; title: string; summary: string; writes: boolean; blocked: boolean; step: NewStep }
  | { kind: "space"; key: string; title: string; step: NewStep };

export function paletteEntries(palette: Palette): PaletteEntry[] {
  const steps: PaletteEntry[] = ADD_KINDS.map((add) => ({
    kind: "step",
    key: `step:${add}`,
    add,
    step: BLANK_STEPS[add],
  }));
  const agents: PaletteEntry[] = palette.agents.map((a) => ({
    kind: "agent",
    key: `agent:${a.key}`,
    title: a.name,
    summary: a.summary,
    team: !!a.builtByTeam,
    step: { type: "agent", config: { agent: a.key, inputs: {}, output_schema: a.outputSchemaRef } },
  }));
  // Anything but a read changes data (the API's rule); a blocked tool says only that it may not be used.
  const tools: PaletteEntry[] = palette.tools.map((tool) => ({
    kind: "tool",
    key: `tool:${tool.ref}`,
    title: `${tool.app}: ${tool.name}`,
    summary: tool.description,
    writes: !isReadTool(tool) && !isBlockedTool(tool),
    blocked: isBlockedTool(tool),
    step: { type: "connector", config: { tool: tool.ref, args: {} } },
  }));
  const spaces: PaletteEntry[] = palette.spaces.map((s) => ({
    kind: "space",
    key: `space:${s.key}`,
    title: s.name,
    step: { type: "memory", config: { op: "recall", space: s.key } },
  }));
  return [...steps, ...agents, ...tools, ...spaces];
}
