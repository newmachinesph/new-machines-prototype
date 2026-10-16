import { describe, expect, it } from "vitest";
import type { EditorIssue } from "@/lib/builder/details";
import { countByStep, serverSubject, withoutCovered, type ServerIssue } from "./issues-panel";

const local: EditorIssue[] = [
  { code: "missingAgent", step: "plan" },
  { code: "unreachable", step: "orphan" },
  { code: "unrouted", step: "verify", outcome: "fail" },
  { code: "missingArg", step: "invoices", arg: "status" },
];
// The first four say what the editor already says (apps/api/app/studio_build.py wording); the rest are the API's alone.
const server: ServerIssue[] = [
  { step: "plan", path: "steps.plan.config.agent", message: "Choose the agent for step plan." },
  { step: "orphan", path: "steps.orphan", message: "Nothing leads to step orphan." },
  { step: "verify", path: "steps.verify.routes.fail", message: "The fail outcome of verify goes nowhere. Connect it." },
  { step: "invoices", path: "steps.invoices.config.args.status", message: "invoices needs a value for status." },
  { step: "verify", path: "steps.verify.routes.pass", message: "The pass outcome of verify goes nowhere. Connect it." },
  { step: "plan", path: "steps.plan.config.output_schema", message: "The result shape of plan does not exist." },
  { path: "steps", message: "The pack never completes. Add an end step that completes the run." },
];

describe("withoutCovered", () => {
  it("drops the API's problems the editor already lists, and keeps the rest", () => {
    expect(withoutCovered(local, server)).toEqual(server.slice(4));
    expect(withoutCovered([], server)).toEqual(server);
  });

  it("counts each step's problems once", () => {
    expect(countByStep(local, server)).toEqual(
      new Map([
        ["plan", 2],
        ["orphan", 1],
        ["verify", 2],
        ["invoices", 1],
      ]),
    );
  });
});

describe("serverSubject", () => {
  const tool = (message: string) => ({ step: "s", path: "steps.s.config.tool", message });
  it("knows the editor's words for the API's step problems", () => {
    expect(serverSubject(tool("s uses x. A pack cannot delete records or move money."))).toBe("s|blockedTool|");
    expect(serverSubject(tool("Choose the app tool for step s."))).toBe("s|missingTool|");
    expect(serverSubject({ step: "s", path: "steps.s.config.args.limit", message: "x has no limit setting." })).toBe(
      "s|unknownArg|limit",
    );
    expect(serverSubject({ step: "s", path: "steps.s.rules", message: "Add the rules s decides with." })).toBe(
      "s|noRules|",
    );
  });

  it("leaves a problem only the API finds, or one without a step, to the API's words", () => {
    expect(serverSubject({ step: "s", path: "steps.s.config.args.a.b", message: "s needs a value for b." })).toBeNull();
    expect(serverSubject({ path: "name", message: "Another pack is already called X." })).toBeNull();
  });
});
