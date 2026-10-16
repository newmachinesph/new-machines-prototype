import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  getWorkflowPackQueryKey,
  listStudioPacksQueryKey,
  listWorkflowPacksQueryKey,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { useInstallPack, useUpgradePack } from "./catalog";

vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/gen/@tanstack/react-query.gen")>()),
  installWorkflowPackMutation: () => ({ mutationFn: async () => ({ slug: "overdue", installed: true }) }),
  upgradeWorkflowPackMutation: () => ({
    mutationFn: async () => {
      throw new Error("UP_TO_DATE");
    },
  }),
}));
vi.mock("./me", async (orig) => ({ ...(await orig<typeof import("./me")>()), useOrgId: () => "org_a1" }));

const wrap = (qc: QueryClient) =>
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };

describe("useInstallPack", () => {
  it("refreshes the Studio's pack list as well as the marketplace, so Added to your workspace is current", async () => {
    const qc = new QueryClient();
    const marketplace = listWorkflowPacksQueryKey();
    const studio = listStudioPacksQueryKey({ path: { org_id: "org_a1" } });
    qc.setQueryData(marketplace, []);
    qc.setQueryData(studio, []);
    const { result } = renderHook(() => useInstallPack(), { wrapper: wrap(qc) });
    await act(() =>
      result.current.mutateAsync({ path: { org_id: "org_a1" }, body: { packSlug: "overdue", capMinor: 1500 } }),
    );
    expect(qc.getQueryState(marketplace)?.isInvalidated).toBe(true);
    expect(qc.getQueryState(studio)?.isInvalidated).toBe(true);
  });
});

describe("useUpgradePack", () => {
  it("refreshes the pack even when the update is refused, so a stale Update available callout goes", async () => {
    const qc = new QueryClient();
    const pack = getWorkflowPackQueryKey({ path: { slug: "overdue" } });
    qc.setQueryData(pack, { slug: "overdue" });
    const { result } = renderHook(() => useUpgradePack("overdue"), { wrapper: wrap(qc) });
    const onError = vi.fn();
    act(() => result.current.upgrade({ onError }));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    await waitFor(() => expect(qc.getQueryState(pack)?.isInvalidated).toBe(true));
  });
});
