import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import type { Run } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { RunPage } from "./run-page";

const query = vi.hoisted(() => ({ run: undefined as Run | undefined }));
vi.mock("@/lib/queries/runs", () => ({
  useRun: () => ({ isPending: false, isError: false, data: query.run, error: null }),
}));
vi.mock("@/lib/queries/catalog", () => ({ usePackName: () => "Overdue invoice follow-up" }));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));
// The run's canvas and receipt have their own tests; the header is what this page adds.
vi.mock("@/components/run-view", () => ({ RunView: () => null }));

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
});
