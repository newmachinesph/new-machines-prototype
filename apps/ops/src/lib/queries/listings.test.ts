import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => {
  const fn = vi.fn().mockResolvedValue({});
  const factory = (name: string) => () => ({
    mutationFn: (options: unknown) => fn(name, options),
  });
  return { fn, factory };
});
vi.mock("@/lib/api/gen/@tanstack/react-query.gen", () => ({
  opsListListingsOptions: vi.fn(() => ({ queryKey: [], queryFn: async () => [] })),
  opsGetListingOptions: vi.fn(() => ({ queryKey: [], queryFn: async () => ({}) })),
  opsApproveListingMutation: calls.factory("approve"),
  opsRequestListingChangesMutation: calls.factory("request-changes"),
  opsRejectListingMutation: calls.factory("reject"),
  opsUnlistListingMutation: calls.factory("unlist"),
  opsRelistListingMutation: calls.factory("relist"),
}));

import { useListingAction } from "./listings";

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(QueryClientProvider, { client: new QueryClient() }, children);

describe("useListingAction", () => {
  beforeEach(() => calls.fn.mockClear());

  it.each(["approve", "request-changes", "reject", "unlist", "relist"] as const)(
    "run(%s) calls the matching mutation with the listing id and reason",
    async (action) => {
      const { result } = renderHook(() => useListingAction(), { wrapper });
      await result.current.run(action, "l1", "A note");
      expect(calls.fn).toHaveBeenCalledWith(action, { path: { listing_id: "l1" }, body: { reason: "A note" } });
    },
  );
});
