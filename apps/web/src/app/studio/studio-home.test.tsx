import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { LiveOnly } from "./live-only";
import { StudioHome } from "./studio-home";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const state = vi.hoisted(() => ({
  workspace: "live",
  role: "owner",
  meError: undefined as Error | undefined,
  agents: [] as unknown[],
  packs: [] as unknown[],
}));

vi.mock("@/lib/queries/me", () => ({
  useMe: () =>
    state.meError
      ? { isPending: false, isError: true, error: state.meError, data: undefined }
      : ok({ workspace: state.workspace, role: state.role }),
  useIsLive: () => !state.meError && state.workspace === "live",
}));
vi.mock("@/lib/queries/studio", () => ({
  useStudioAgents: () => ok(state.agents),
  useStudioPacks: () => ok(state.packs),
}));

/** The error panel's Retry resets queries, so it needs a client. */
const Gate = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <LiveOnly>{children}</LiveOnly>
  </QueryClientProvider>
);

describe("Studio home", () => {
  beforeEach(() => {
    state.workspace = "live";
    state.role = "owner";
    state.meError = undefined;
    state.agents = [];
    state.packs = [];
  });

  it("says what the Studio is for and links to new agents and packs", () => {
    renderWithIntl(<StudioHome />);
    expect(screen.getByText("Only your company sees what you build here")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New agent" })).toHaveAttribute("href", "/studio/agents/new");
    expect(screen.getByRole("link", { name: "New pack" })).toHaveAttribute("href", "/studio/packs/new");
    expect(screen.getByText(/No agents yet/)).toBeInTheDocument();
  });

  it("counts what the org has built", () => {
    state.agents = [{ key: "a" }, { key: "b" }];
    state.packs = [{ key: "p" }];
    renderWithIntl(<StudioHome />);
    expect(screen.getByRole("link", { name: "2 agents" })).toHaveAttribute("href", "/studio/agents");
    expect(screen.getByRole("link", { name: "1 pack" })).toHaveAttribute("href", "/studio/packs");
  });

  it("tells a member that only owners and admins build, and offers no New links", () => {
    state.role = "member";
    renderWithIntl(<StudioHome />);
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New agent" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New pack" })).toBeNull();
  });

  it("shows a headed notice instead of the Studio in the demo workspace", () => {
    state.workspace = "demo";
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Developer Studio" })).toBeInTheDocument();
    expect(screen.getByText("The Studio is part of the live workspace")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("shows the Studio in a live workspace", () => {
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByText("studio")).toBeInTheDocument();
    expect(screen.queryByText(/live workspace/)).toBeNull();
  });

  it("shows a failed /v1/me as an error inside the shell, never as a demo", () => {
    state.meError = new ApiError(500, "ERROR", "down");
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("This page could not load");
    expect(screen.queryByText(/part of the live workspace/)).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("keeps the skeleton on a 401, since the client is already signing out", () => {
    state.meError = new ApiError(401, "UNAUTHORIZED", "Sign in");
    renderWithIntl(
      <Gate>
        <p>studio</p>
      </Gate>,
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/live workspace/)).toBeNull();
    expect(screen.queryByText("studio")).toBeNull();
  });

  it("speaks Japanese", () => {
    state.agents = [{ key: "a" }, { key: "b" }];
    renderWithIntl(<StudioHome />, { locale: "ja" });
    expect(screen.getByRole("link", { name: "新しいエージェント" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "エージェント 2 件" })).toBeInTheDocument();
  });
});
