import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import type { Run } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { RunPage } from "./run-page";

const query = vi.hoisted(() => ({ run: undefined as Run | undefined, shown: undefined as Run | undefined }));
vi.mock("@/lib/queries/runs", () => ({
  useRun: () => ({ isPending: false, isError: false, data: query.run, error: null }),
}));
const AGENT_KEY = "org-5c8192d7129c2fa2-qa-inbox-reader-a2";
vi.mock("@/lib/queries/catalog", () => ({
  usePackName: () => "Overdue invoice follow-up",
  usePacks: () => ({ data: undefined }),
  useAgentById: () => (id: string) => (id === AGENT_KEY ? { id, name: "QA inbox reader" } : undefined),
}));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
// The run's canvas and receipt have their own tests; the header is what this page adds.
vi.mock("@/components/run-view", () => ({
  RunView: ({ run }: { run: Run }) => {
    query.shown = run;
    return null;
  },
}));

describe("RunPage", () => {
  it("labels a sandbox test run, and only such a run", () => {
    query.run = { ...RUN_1042, sandboxTest: true };
    const { unmount } = renderWithIntl(<RunPage id={RUN_1042.id} />);
    expect(screen.getByText("Sandbox test")).toBeInTheDocument();
    unmount();
    query.run = { ...RUN_1042, sandboxTest: undefined };
    renderWithIntl(<RunPage id={RUN_1042.id} />);
    expect(screen.queryByText("Sandbox test")).toBeNull();
    expect(screen.getByText("Overdue invoice follow-up")).toBeInTheDocument();
  });

  // QA F-12: an agent step read "Org 5c8192d7129c2fa2 qa inbox reader a2", its raw key with the org id.
  it("hands the run view each agent step under the agent's display name", () => {
    const agentStep = RUN_1042.nodes.find((n) => n.type === "agent")!;
    query.run = {
      ...RUN_1042,
      nodes: RUN_1042.nodes.map((n) =>
        n.id === agentStep.id
          ? { ...n, label: "Org 5c8192d7129c2fa2 qa inbox reader a2", version: `${AGENT_KEY}@1` }
          : n,
      ),
    };
    renderWithIntl(<RunPage id={RUN_1042.id} />);
    const shown = query.shown!.nodes.find((n) => n.id === agentStep.id)!;
    expect(shown.label).toBe("QA inbox reader");
    expect(JSON.stringify(query.shown!.nodes.map((n) => n.label))).not.toMatch(/5c8192d7129c2fa2/);
  });

  it("says the run waits for a reviewer or an approval, not that it is starting", () => {
    query.run = { ...RUN_1042, summary: "Starting.", status: "WAITING_FOR_HUMAN" };
    const { unmount } = renderWithIntl(<RunPage id={RUN_1042.id} />);
    expect(screen.getByText("Waiting for a reviewer to finish their step.")).toBeInTheDocument();
    expect(screen.queryByText("Starting.")).toBeNull();
    unmount();
    query.run = { ...RUN_1042, summary: "Starting.", status: "WAITING_FOR_EVENT" };
    const ja = renderWithIntl(<RunPage id={RUN_1042.id} />, { locale: "ja" });
    expect(screen.getByText("続行する前に、あなたの承認を待っています。")).toBeInTheDocument();
    ja.unmount();
    query.run = {
      ...RUN_1042,
      summary: "Starting.",
      status: "RUNNING",
      nodes: RUN_1042.nodes.map((n) => ({ ...n, status: "CREATED" as const })),
    };
    renderWithIntl(<RunPage id={RUN_1042.id} />);
    expect(screen.getByText("Starting.")).toBeInTheDocument();
  });

  it("calls a run stopped by a declined approval Declined, not Failed", () => {
    query.run = { ...RUN_1042, status: "FAILED", stopReason: "declined", summary: "The approval was declined." };
    renderWithIntl(<RunPage id={RUN_1042.id} />);
    expect(screen.getByText("Declined")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).toBeNull();
  });
});
