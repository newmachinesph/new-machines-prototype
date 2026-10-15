import { describe, expect, it } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import type { Run } from "@/lib/types";
import { changed, moneyText, toolUse } from "./run-facts";

type Call = NonNullable<Run["nodes"][number]["toolCalls"]>[number];

const call = (over: Partial<Call>): Call => ({
  id: "tc",
  app: "Gmail",
  action: "create draft",
  capability: "mail.write",
  status: "CONFIRMED",
  policy: "PERMIT",
  detail: "",
  ...over,
});

const run = (calls: Call[], granted: boolean): Run => ({
  ...RUN_1042,
  nodes: [
    {
      id: "send",
      type: "connector",
      label: "Send",
      actor: "machine",
      status: "COMPLETED",
      x: 0,
      y: 0,
      toolCalls: calls,
    },
  ],
  edges: [{ from: "approve", to: "send", label: "granted", taken: granted }],
});

describe("toolUse and changed", () => {
  it("counts a real write after a granted approval", () => {
    const uses = toolUse(run([call({ actionClass: "write" }), call({ actionClass: "write" })], true));
    expect(uses).toEqual([
      { app: "Gmail", action: "create draft", kind: "write", ran: 2, notRun: 0, approval: "granted", sandbox: "none" },
    ]);
    expect(changed(uses)).toBe("afterApproval");
  });

  it("flags a real write with no approval step, and counts calls that did not run", () => {
    const uses = toolUse(run([call({}), call({ status: "DENIED", policy: "DENY" })], false));
    expect(uses[0]).toMatchObject({ kind: "write", ran: 1, notRun: 1, approval: "none" });
    expect(changed(uses)).toBe("withoutApproval");
  });

  it("reads the action class from the capability when an older run has none", () => {
    const uses = toolUse(run([call({ action: "list threads", capability: "mail.read", mocked: true })], false));
    expect(uses[0]).toMatchObject({ kind: "read", approval: "n/a", sandbox: "all" });
    expect(changed(uses)).toBe("nothing");
  });

  it("marks a group that mixes sandbox and real calls as partly sandbox, and counts it as a real write", () => {
    const uses = toolUse(run([call({ mocked: true }), call({ mocked: false })], true));
    expect(uses[0]).toMatchObject({ ran: 2, sandbox: "some", approval: "granted" });
    expect(changed(uses)).toBe("afterApproval");
  });

  it("says nothing changed when every write was simulated, and when no app was called", () => {
    expect(changed(toolUse(run([call({ mocked: true })], true)))).toBe("simulated");
    expect(changed(toolUse(run([], true)))).toBe("noCalls");
  });
});

describe("moneyText", () => {
  it("writes an amount the API sent as '70.40 USD' the interface's way, and leaves other values alone", () => {
    expect(moneyText("-70.40 USD", "en-US")).toBe("−$70.40");
    expect(moneyText("89.66 USD", "en-US")).toBe("$89.66");
    expect(moneyText("1200 JPY", "ja-JP")).toBe("￥1,200");
    expect(moneyText("12", "en-US")).toBe("12");
    expect(moneyText("2 pages", "en-US")).toBe("2 pages");
    expect(moneyText("2 PDF", "en-US")).toBe("2 PDF");
    expect(moneyText("3 CSV", "en-US")).toBe("3 CSV");
  });
});
