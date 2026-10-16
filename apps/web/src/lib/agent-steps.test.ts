import { describe, expect, it } from "vitest";
import type { RunNode } from "@/lib/types";
import { nameAgentSteps } from "./agent-steps";

const node = (over: Partial<RunNode>): RunNode =>
  ({ id: "n", type: "agent", label: "", actor: "machine", status: "DONE", x: 0, y: 0, ...over }) as RunNode;

// A workspace's own agent key is `org-<id>--<name>`. The run projection used to label such a step with the key
// in words (every "-" a space, then capitalized), which leaves a double space where the "--" was.
const ORG_KEY = "org-5c8192d7129c2fa2--qa-inbox-reader-a2";
const ORG_KEY_IN_WORDS = "Org 5c8192d7129c2fa2  qa inbox reader a2";
const names: Record<string, string> = { [ORG_KEY]: "QA inbox reader", "finance-agent": "Finance Agent" };
const nameOf = (key: string) => names[key];

describe("nameAgentSteps", () => {
  it("names an agent step by the agent's display name, never its key", () => {
    const [step] = nameAgentSteps([node({ label: ORG_KEY_IN_WORDS, version: `${ORG_KEY}@1` })], nameOf, "AI agent");
    expect(step!.label).toBe("QA inbox reader");
  });

  it("names a platform agent by its display name too", () => {
    const [step] = nameAgentSteps([node({ label: "Finance agent", version: "finance-agent@3" })], nameOf, "AI agent");
    expect(step!.label).toBe("Finance Agent");
  });

  it.each([
    ["the projection's double-spaced key in words", "Org 0a1b2c3d4e5f6071  helper"],
    ["the key in words with single spaces", "Org 0a1b2c3d4e5f6071 helper"],
    ["the bare key", "org-0a1b2c3d4e5f6071--helper"],
    ["any label that carries the org id", "Helper (org-0a1b2c3d4e5f6071)"],
  ])("never shows a workspace's own agent key it cannot name (%s): the step reads as an AI agent", (_, label) => {
    const [step] = nameAgentSteps([node({ label, version: "org-0a1b2c3d4e5f6071--helper@2" })], nameOf, "AI agent");
    expect(step!.label).toBe("AI agent");
  });

  it("keeps the agent's name the run already gives a workspace's agent it cannot name itself", () => {
    const [step] = nameAgentSteps(
      [node({ label: "Helper", version: "org-0a1b2c3d4e5f6071--helper@2" })],
      nameOf,
      "AI agent",
    );
    expect(step!.label).toBe("Helper");
  });

  it("keeps the label of a step it has nothing better for, and leaves other steps alone", () => {
    const steps = [
      node({ label: "Ops agent", version: "ops-agent@1" }),
      node({ type: "connector", label: "Gmail: list threads", version: "gmail@1" }),
      node({ label: "Writer" }),
    ];
    expect(nameAgentSteps(steps, nameOf, "AI agent")).toEqual(steps);
  });

  it("returns new steps, not the same ones changed", () => {
    const steps = [node({ label: ORG_KEY_IN_WORDS, version: `${ORG_KEY}@1` })];
    const named = nameAgentSteps(steps, nameOf, "AI agent");
    expect(named[0]).not.toBe(steps[0]);
    expect(steps[0]!.label).toBe(ORG_KEY_IN_WORDS);
  });
});
