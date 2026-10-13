import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { DefinitionDetailView } from "./definition-detail";

const version = (n: number) => ({
  version: n,
  digest: `d${n}`,
  source: n === 1 ? ("file" as const) : ("console" as const),
  publishedBy: n === 1 ? "definitions" : "ops@newmachin.es",
  reason: n === 1 ? "Applied from files" : "Raise the turn limit",
  publishedAt: "2026-10-13T09:00:00Z",
});

const detail = (shown: number, latest = 2): DefinitionDetail => ({
  summary: {
    kind: "agent",
    key: "finance-agent",
    name: "Finance agent",
    version: shown,
    digest: `d${shown}`,
    source: "console",
    publishedBy: "ops@newmachin.es",
    publishedAt: "2026-10-13T09:00:00Z",
  },
  versions: Array.from({ length: latest }, (_, i) => version(latest - i)),
  yaml: `kind: agent\nkey: finance-agent\nname: Finance agent\n# v${shown}\n`,
  files: { "instructions.md": "Hi" },
  body: { name: "Finance agent" },
  refs: [{ kind: "models", key: "default" }],
  usedBy: [{ kind: "pack", key: "order-payment-reconciliation" }],
});

const state = vi.hoisted(() => ({
  canWrite: true,
  version: null as number | null,
  from: null as string | null,
  setVersion: vi.fn(),
  setFrom: vi.fn(),
  queries: {} as Record<string, unknown>,
  exportFiles: vi.fn(),
  download: vi.fn(),
  toast: vi.fn(),
  mounts: 0,
}));

vi.mock("nuqs", () => ({
  parseAsInteger: {},
  parseAsString: {},
  useQueryState: (key: string) => (key === "version" ? [state.version, state.setVersion] : [state.from, state.setFrom]),
}));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => state.canWrite }));
vi.mock("@/lib/queries/definitions", () => ({
  useDefinition: (_kind: string, key: string) => state.queries[key],
  useFetchExport: () => state.exportFiles,
}));
vi.mock("@/lib/download", () => ({ downloadText: state.download }));
vi.mock("@/components/base", async (orig) => ({ ...(await orig<object>()), useToast: () => state.toast }));
vi.mock("./definition-editor", async () => {
  const { useState } = await import("react");
  return {
    DefinitionEditor: (p: {
      initial: { yaml: string; files: Record<string, string> };
      isNew?: boolean;
      nextVersion: number;
      defKey: string;
      onPublished?: (d: unknown) => void;
    }) => {
      // Counts mounts, so a test can tell a re-render (draft kept) from a remount (draft lost).
      const [mount] = useState(() => ++state.mounts);
      return (
        <div data-testid="editor" data-new={String(Boolean(p.isNew))} data-next={p.nextVersion} data-mount={mount}>
          <pre>{p.initial.yaml}</pre>
          <span>{Object.keys(p.initial.files).join(",")}</span>
          <button type="button" onClick={() => p.onPublished?.({})}>
            stub publish
          </button>
        </div>
      );
    },
  };
});

const ok = (data: unknown) => ({ isPending: false, isError: false, data });
const failed = (error: unknown) => ({ isPending: false, isError: true, error, data: undefined });

const renderView = (kind = "agent", defKey = "finance-agent") =>
  render(
    <UiProviders>
      <DefinitionDetailView kind={kind} defKey={defKey} />
    </UiProviders>,
  );

describe("DefinitionDetailView", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.version = null;
    state.from = null;
    state.setVersion.mockClear();
    state.setFrom.mockClear();
    state.download.mockClear();
    state.toast.mockClear();
    state.exportFiles.mockReset();
    state.queries = { "finance-agent": ok(detail(2)) };
  });

  it("shows the latest version in the editor with its history and references", () => {
    renderView();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Finance agent");
    expect(screen.getByTestId("editor")).toHaveAttribute("data-next", "3");
    expect(screen.getByText(/# v2/)).toBeInTheDocument();

    const versions = screen.getByRole("list", { name: "Versions" });
    expect(within(versions).getByRole("link", { name: /v1/ })).toHaveAttribute(
      "href",
      "/definitions/agent/finance-agent?version=1",
    );
    expect(within(versions).getByText("Raise the turn limit")).toBeInTheDocument();
    expect(within(versions).getByRole("link", { name: /v2/ })).toHaveAttribute("aria-current", "page");

    expect(screen.getByRole("link", { name: "models/default" })).toHaveAttribute("href", "/definitions/models/default");
    expect(screen.getByRole("link", { name: "pack/order-payment-reconciliation" })).toBeInTheDocument();
  });

  it("says when an older version is shown and that publishing it makes it the latest", () => {
    state.version = 1;
    state.queries = { "finance-agent": ok(detail(1)) };
    renderView();
    expect(screen.getByText(/Viewing v1 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/# v1/)).toBeInTheDocument();
    expect(screen.getByTestId("editor")).toHaveAttribute("data-next", "3");
  });

  it("exports each file of the version shown", async () => {
    const user = userEvent.setup();
    state.exportFiles.mockResolvedValue({
      files: { "agents/finance-agent/agent.yaml": "kind: agent", "agents/finance-agent/instructions.md": "Hi" },
    });
    renderView();
    await user.click(screen.getByRole("button", { name: "Export files" }));
    await waitFor(() => expect(state.download).toHaveBeenCalledTimes(2));
    expect(state.exportFiles).toHaveBeenCalledWith("agent", "finance-agent", null);
    expect(state.download).toHaveBeenCalledWith("agents__finance-agent__agent.yaml", "kind: agent");
    // The browser may still block some of them, so the toast says what was started, not what was saved.
    await waitFor(() =>
      expect(state.toast).toHaveBeenCalledWith(
        "Started 2 downloads",
        "Allow multiple downloads if your browser asks. Each name keeps its folder path.",
      ),
    );
  });

  it("keeps the editor mounted when a newer version arrives, and remounts it for another version", () => {
    const view = renderView();
    const first = screen.getByTestId("editor").getAttribute("data-mount");
    state.queries = { "finance-agent": ok(detail(3, 3)) };
    view.rerender(
      <UiProviders>
        <DefinitionDetailView kind="agent" defKey="finance-agent" />
      </UiProviders>,
    );
    expect(screen.getByTestId("editor")).toHaveAttribute("data-mount", first);
    expect(screen.getByTestId("editor")).toHaveAttribute("data-next", "4");

    state.version = 1;
    state.queries = { "finance-agent": ok(detail(1, 3)) };
    view.rerender(
      <UiProviders>
        <DefinitionDetailView kind="agent" defKey="finance-agent" />
      </UiProviders>,
    );
    expect(screen.getByTestId("editor")).not.toHaveAttribute("data-mount", first);
  });

  it("explains that definitions need the local runtime when it is off", () => {
    state.queries = { "finance-agent": failed(new ApiError(503, "RUNTIME_UNAVAILABLE", "Off.")) };
    renderView();
    expect(screen.getByText("Definitions need the local runtime (Postgres). See README.")).toBeInTheDocument();
  });

  it("says so for an unknown definition or kind", () => {
    state.queries = { nope: failed(new ApiError(404, "NOT_FOUND", "No definition agent/nope.")) };
    renderView("agent", "nope");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("No agent called nope");
    renderView("agents", "x");
    expect(screen.getByRole("heading", { level: 1, name: /No definition kind agents/ })).toBeInTheDocument();
  });

  it("opens a new definition from a copy of another, with its key swapped", async () => {
    const user = userEvent.setup();
    state.from = "finance-agent";
    state.queries = {
      "billing-agent": failed(new ApiError(404, "NOT_FOUND", "No definition agent/billing-agent.")),
      "finance-agent": ok(detail(2)),
    };
    renderView("agent", "billing-agent");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("New agent: billing-agent");
    const editor = screen.getByTestId("editor");
    expect(editor).toHaveAttribute("data-new", "true");
    expect(editor).toHaveAttribute("data-next", "1");
    expect(within(editor).getByText(/key: billing-agent/)).toBeInTheDocument();
    expect(within(editor).getByText(/name: Copy of Finance agent/)).toBeInTheDocument();
    expect(within(editor).getByText("instructions.md")).toBeInTheDocument();

    await user.click(within(editor).getByRole("button", { name: "stub publish" }));
    expect(state.setFrom).toHaveBeenCalledWith(null);
  });

  it("does not open the new-definition editor for support", () => {
    state.canWrite = false;
    state.from = "finance-agent";
    state.queries = {
      "billing-agent": failed(new ApiError(404, "NOT_FOUND", "No definition agent/billing-agent.")),
      "finance-agent": ok(detail(2)),
    };
    renderView("agent", "billing-agent");
    expect(screen.queryByTestId("editor")).toBeNull();
    expect(screen.getByText(/Support access is read-only/)).toBeInTheDocument();
  });
});
