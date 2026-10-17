import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { listMemoryQueryKey } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { ListMemoryResponse } from "@/lib/api/gen/types.gen";
import { useAddMemory } from "./workspace";

const ADDED = {
  id: "mem_9",
  text: "Never refund an opened item without a person's approval.",
  scope: "Organization",
  scopeName: "Retail & Commerce company knowledge",
  state: "APPROVED",
  source: "Your team",
  proposedBy: "uid_ana",
  createdAt: "2026-10-17T10:00:00Z",
} as const;
const OLDER = { ...ADDED, id: "mem_1", text: "Orders over $500 need a person to confirm.", source: "Definitions seed" };

vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<object>()),
  addMemoryMutation: () => ({ mutationFn: async () => ADDED }),
}));

describe("useAddMemory", () => {
  it("heads the memory list with the new item, in use, and refetches the list", async () => {
    const qc = new QueryClient();
    const key = listMemoryQueryKey();
    qc.setQueryData<ListMemoryResponse>(key, [OLDER]);
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useAddMemory(), { wrapper });
    await act(() => result.current.mutateAsync({ body: { space: "retail-commerce", text: ADDED.text } }));
    const rows = qc.getQueryData<ListMemoryResponse>(key);
    expect(rows?.map((m) => m.id)).toEqual(["mem_9", "mem_1"]);
    expect(rows?.[0]).toMatchObject({ state: "APPROVED", source: "Your team" });
    expect(rows?.[0]?.retracted).toBeUndefined(); // in use, not retracted
    expect(invalidate).toHaveBeenCalledWith({ queryKey: key });
  });
});
