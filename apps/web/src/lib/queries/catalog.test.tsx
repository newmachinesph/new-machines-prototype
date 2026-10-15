import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { listStudioPacksQueryKey, listWorkflowPacksQueryKey } from "@/lib/api/gen/@tanstack/react-query.gen";
import { useInstallPack } from "./catalog";

vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<typeof import("@/lib/api/gen/@tanstack/react-query.gen")>()),
  installWorkflowPackMutation: () => ({ mutationFn: async () => ({ slug: "overdue", installed: true }) }),
}));

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
