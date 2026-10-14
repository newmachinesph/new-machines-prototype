import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { listOrgReviewersQueryKey } from "@/lib/api/gen/@tanstack/react-query.gen";
import { useSetReviewerNetwork } from "./reviewers";

const ANSWER = { allowNetwork: true, reviewers: [] };
vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<object>()),
  setReviewerNetworkMutation: () => ({ mutationFn: async () => ANSWER }),
}));

describe("useSetReviewerNetwork", () => {
  it("writes the answer into the reviewers list at once", async () => {
    const qc = new QueryClient();
    const key = listOrgReviewersQueryKey({ path: { org_id: "org_new" } });
    qc.setQueryData(key, { allowNetwork: false, reviewers: [] });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useSetReviewerNetwork(), { wrapper });
    const seen = vi.fn();
    await act(() =>
      result.current.mutateAsync(
        { path: { org_id: "org_new" }, body: { allow: true } },
        { onSuccess: () => seen(qc.getQueryData(key)) },
      ),
    );
    // The caller's own onSuccess (the toast) already sees the new value.
    expect(seen).toHaveBeenCalledWith(ANSWER);
    expect(qc.getQueryData(key)).toEqual(ANSWER);
  });
});
