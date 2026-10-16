/**
 * Step types and their outcomes, as the API's builder knows them (`apps/api/app/studio_build.py`: ROUTES,
 * STEP_ID). The API stays the authority; these let the editor draw handles and refuse bad connections at once.
 */
import type { DecisionRules, StepDraft } from "@/lib/api/gen/types.gen";
import { FAILURE_ROUTES } from "@/lib/terminal-stubs";
import type { Actor } from "@/lib/types";

export type StepType = StepDraft["type"];

export const STEP_TYPES: readonly StepType[] = [
  "trigger",
  "memory",
  "connector",
  "agent",
  "decision",
  "human_workforce",
  "approval",
  "verification",
  "end",
];

/** The outcomes each step type routes, in order. A decision's come from its rules; an end has none. */
export const ROUTES: Record<StepType, readonly string[]> = {
  trigger: ["next"],
  memory: ["next"],
  agent: ["next"],
  connector: ["ok", "denied", "error"],
  human_workforce: ["resolved", "rejected", "timeout"],
  approval: ["granted", "denied", "timeout"],
  verification: ["pass", "fail"],
  decision: [],
  end: [],
};

/** Every fixed outcome, for labels. A decision's outcomes are the builder's own words. */
export const KNOWN_OUTCOMES: ReadonlySet<string> = new Set(Object.values(ROUTES).flat());

/** Outcomes that lead away from the happy path: the run canvas's own set, so both canvases agree. */
export const FAILURE_OUTCOMES: ReadonlySet<string> = FAILURE_ROUTES;

/** Who does the step, for its colour: the API projection's NODE_ACTORS, so runs and the editor agree. */
export const STEP_ACTOR: Record<StepType, Actor> = {
  trigger: "buyer",
  memory: "system",
  connector: "machine",
  agent: "machine",
  decision: "machine",
  verification: "machine",
  human_workforce: "human",
  approval: "buyer",
  end: "system",
};

/** Drawn as the narrow card, as on the run canvas. */
export const SMALL_STEPS: ReadonlySet<StepType> = new Set(["trigger", "end"]);

/** A step id is a CEL identifier (`nodes.<id>.output`): lowercase letters, digits and underscores. */
export const STEP_ID = /^[a-z][a-z0-9_]{0,39}$/;

export const ID_PREFIX: Record<StepType, string> = {
  trigger: "start",
  memory: "recall",
  connector: "app",
  agent: "agent",
  decision: "check",
  human_workforce: "review",
  approval: "approve",
  verification: "verify",
  end: "end",
};

export type StepShape = { type: StepType; rules?: DecisionRules };

/** The outcomes `step` must route, in order: fixed per type; a decision's rule routes, then its default. */
export function outcomesOf(step: StepShape): string[] {
  if (step.type !== "decision") return [...ROUTES[step.type]];
  if (!step.rules) return [];
  const routes = [...(step.rules.rules ?? []).map((r) => r.route), step.rules.default.route];
  const onError = evaluatorErrorRoute(step.rules);
  return [...new Set(onError ? [...routes, onError] : routes)];
}

/** Where a decision's model step goes when it fails: the Studio never edits the evaluator, but it routes this. */
function evaluatorErrorRoute(rules: DecisionRules): string | undefined {
  const onError: unknown = (rules.evaluator as { on_error?: unknown } | undefined)?.on_error;
  const route = typeof onError === "object" && onError !== null ? (onError as { route?: unknown }).route : undefined;
  return typeof route === "string" && route !== "" ? route : undefined;
}

/** The first free id for a new step of `type`: review, then review_2, review_3 and so on. */
export function nextStepId(type: StepType, taken: Iterable<string>): string {
  const used = new Set(taken);
  const base = ID_PREFIX[type];
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) if (!used.has(`${base}_${n}`)) return `${base}_${n}`;
}
