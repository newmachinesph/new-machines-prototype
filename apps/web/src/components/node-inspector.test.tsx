import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import type { RunNode } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { NodeInspector } from "./node-inspector";

vi.mock("@/lib/queries/tasks", () => ({ useTask: () => ({ data: undefined, isPending: false }) }));

const decide = RUN_1042.nodes.find((n) => n.id === "decide")!;

/** A decision step as the live API projects it: codes in the result and the reason codes. */
const live: RunNode = {
  ...decide,
  humanTaskId: undefined,
  output: "HUMAN_REVIEW: MISMATCHES_FOUND",
  decision: {
    ...decide.decision!,
    reasonCodes: ["MISMATCHES_FOUND"],
    policy: {
      id: "poldec_run_2011_check_1",
      ref: "policy/default",
      verdict: "PERMIT",
      reasonCodes: ["RULES_EVALUATED"],
      actor: "Policy engine",
    },
    approval: undefined,
  },
};

const connector: RunNode = {
  id: "orders",
  type: "connector",
  label: "Shopify: list orders",
  subtitle: "read access",
  actor: "machine",
  status: "COMPLETED",
  x: 0,
  y: 0,
  toolCalls: [
    {
      id: "tool_7",
      app: "Shopify",
      action: "list orders",
      capability: "orders.read",
      status: "CONFIRMED",
      policy: "PERMIT",
      detail: "ACTION_CLASS_PERMITTED",
      mocked: true,
    },
  ],
};

const inDetails = (text: string | RegExp) => screen.getByText(text).closest("details");

describe("NodeInspector", () => {
  it("writes a decision's result and reason codes as sentences, with the codes and ids under technical details", () => {
    renderWithIntl(<NodeInspector node={live} />);
    expect(screen.getByText("Needs a person: Some orders and payments do not match")).toBeInTheDocument();
    expect(screen.getAllByText("Some orders and payments do not match")).not.toHaveLength(0);
    expect(screen.getByText("Decided by the pack's rules")).toBeInTheDocument();
    expect(inDetails("policy/default")).not.toBeNull();
    expect(inDetails("poldec_run_2011_check_1")).not.toBeNull();
    expect(inDetails("MISMATCHES_FOUND")).not.toBeNull();
    expect(inDetails("RULES_EVALUATED")).not.toBeNull();
    expect(screen.getAllByText("Technical details")).toHaveLength(1);
  });

  it("names no model vendor in the evaluator chain", () => {
    renderWithIntl(<NodeInspector node={decide} />);
    expect(document.body.textContent).not.toMatch(/gemini/i);
    expect(screen.getByText("AI model")).toBeInTheDocument();
  });

  it("puts a tool call's policy code in words and its capability under technical details", () => {
    renderWithIntl(<NodeInspector node={connector} />);
    expect(screen.getByText("Reads only")).toBeInTheDocument();
    expect(screen.getByText("Allowed: your policies permit this kind of action")).toBeInTheDocument();
    expect(screen.queryByText("ACTION_CLASS_PERMITTED")).not.toBeInTheDocument();
    expect(inDetails("orders.read")).not.toBeNull();
    expect(inDetails("tool_7")).not.toBeNull();
  });
});

describe("NodeInspector copy from the API", () => {
  it("never names a model vendor in a step's subtitle, chain note or explanation", () => {
    const node: RunNode = {
      ...live,
      subtitle: "Rules, then Gemini",
      decision: {
        ...live.decision!,
        chain: [{ kind: "gemini", verdict: "APPROVED", note: "Gemini checked the photo." }],
        explanation: "Rules and model agree.",
      },
    };
    renderWithIntl(<NodeInspector node={node} />);
    expect(screen.getByText("Rules, then the AI model")).toBeInTheDocument();
    expect(screen.getByText("The AI model checked the photo.")).toBeInTheDocument();
    expect(screen.getByText("Rules and the AI model agree.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/gemini|model/i);
  });

  it("reads a waiting note without the approval id", () => {
    renderWithIntl(<NodeInspector node={{ ...live, note: "Waiting on apr_run_2011_approve_write_1." }} />);
    expect(screen.getByText("Waiting for approval.")).toBeInTheDocument();
    expect(screen.queryByText(/apr_run_2011/)).not.toBeInTheDocument();
  });

  it("skips empty rows under technical details", () => {
    const node: RunNode = {
      ...live,
      decision: { ...live.decision!, reasonCodes: [], policy: { ...live.decision!.policy, reasonCodes: [] } },
    };
    renderWithIntl(<NodeInspector node={node} />);
    expect(screen.queryByText("Evaluator codes")).not.toBeInTheDocument();
    expect(screen.queryByText("Policy codes")).not.toBeInTheDocument();
    expect(screen.getByText("policy/default")).toBeInTheDocument();
  });

  it("names the decision model in plain words and never by its product name", () => {
    const node: RunNode = {
      ...live,
      subtitle: "Decision model",
      decision: {
        ...live.decision!,
        evaluator: { kind: "jev", label: "Decision model", configVersion: "lead-screen@v1" },
        chain: [
          { kind: "jev", verdict: "PASS", note: "Answered for 5 items; 3 kept." },
          { kind: "rules", verdict: "APPROVED", note: "Some emails look like real enquiries." },
        ],
      },
    };
    renderWithIntl(<NodeInspector node={node} />);
    expect(screen.getAllByText("Decision model").length).toBeGreaterThan(0);
    expect(screen.getByText("Answered for 5 items; 3 kept.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/\bjev\b|typesafe|openrouter/i);
  });

  it("names the decision model in Japanese", () => {
    const node: RunNode = {
      ...live,
      decision: { ...live.decision!, chain: [{ kind: "jev", verdict: "ERROR", note: "The decision model could not be reached." }] },
    };
    renderWithIntl(<NodeInspector node={node} />, { locale: "ja" });
    expect(screen.getAllByText("判断モデル").length).toBeGreaterThan(0);
  });
});
