import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getStudioPackQueryKey, listStudioAgentsQueryKey } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { StudioAgent } from "@/lib/api/gen/types.gen";
import { useSaveStudioAgent, useStudioPacks } from "./studio";

const AGENT: StudioAgent = {
  key: "org-a1--invoice-helper",
  version: 2,
  publishedAt: "2026-10-14T00:00:00Z",
  publishedBy: "u1",
  draft: { name: "Invoice helper", summary: "Finds open invoices.", instructions: "Read them." },
};
const state = vi.hoisted(() => ({ workspace: "live", fetchPacks: vi.fn(async () => []) }));

vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => {
  const real = await orig<typeof import("@/lib/api/gen/@tanstack/react-query.gen")>();
  const listStudioPacksOptions: typeof real.listStudioPacksOptions = (o) => ({
    ...real.listStudioPacksOptions(o),
    queryFn: state.fetchPacks,
  });
  return { ...real, listStudioPacksOptions, saveStudioAgentMutation: () => ({ mutationFn: async () => AGENT }) };
});
vi.mock("@/lib/queries/me", async (orig) => ({
  ...(await orig<typeof import("@/lib/queries/me")>()),
  useMe: () => ({ isPending: false, isError: false, data: { orgId: "org_a1", workspace: state.workspace } }),
  useIsLive: () => state.workspace === "live",
}));

const wrap = (qc: QueryClient) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };

describe("Studio queries", () => {
  beforeEach(() => {
    state.workspace = "live";
    state.fetchPacks.mockClear();
  });

  it("never requests in the demo workspace", () => {
    state.workspace = "demo";
    const { result } = renderHook(() => useStudioPacks(), { wrapper: wrap(new QueryClient()) });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.isPending).toBe(true);
    expect(state.fetchPacks).not.toHaveBeenCalled();
  });

  it("requests in a live workspace", async () => {
    renderHook(() => useStudioPacks(), { wrapper: wrap(new QueryClient()) });
    await waitFor(() => expect(state.fetchPacks).toHaveBeenCalledTimes(1));
  });
});

describe("useSaveStudioAgent", () => {
  it("refreshes the packs the save rebuilt, as well as the agents", async () => {
    const qc = new QueryClient();
    const pack = getStudioPackQueryKey({ path: { org_id: "org_a1", key: "org-a1--overdue" } });
    const agents = listStudioAgentsQueryKey({ path: { org_id: "org_a1" } });
    qc.setQueryData(pack, { key: "org-a1--overdue", version: 1 });
    qc.setQueryData(agents, []);
    const { result } = renderHook(() => useSaveStudioAgent(), { wrapper: wrap(qc) });
    await act(() =>
      result.current.mutateAsync({
        path: { org_id: "org_a1", key: AGENT.key },
        body: { draft: AGENT.draft, baseVersion: 1 },
      }),
    );
    expect(qc.getQueryState(pack)?.isInvalidated).toBe(true);
    expect(qc.getQueryState(agents)?.isInvalidated).toBe(true);
  });
});
