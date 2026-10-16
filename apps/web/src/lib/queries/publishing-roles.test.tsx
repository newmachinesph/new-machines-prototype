import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePublisher } from "./publisher";
import { useStudioEarnings, useStudioListing, useStudioListings } from "./publishing";

const { read, options } = vi.hoisted(() => {
  const read = vi.fn();
  return { read, options: (name: string) => () => ({ queryKey: [name], queryFn: read }) };
});
const who = vi.hoisted(() => ({ role: "owner" }));
vi.mock("./me", async (orig) => ({
  ...(await orig<object>()),
  useMe: () => ({ isError: false, data: { orgId: "org_1", role: who.role, workspace: "live" } }),
  useIsLive: () => true,
}));
vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<object>()),
  listStudioListingsOptions: options("listings"),
  getStudioListingOptions: options("listing"),
  getStudioEarningsOptions: options("earnings"),
  getPublisherOptions: options("publisher"),
}));

const HOOKS = {
  listings: useStudioListings,
  listing: function useOneListing() {
    return useStudioListing("lst_1");
  },
  earnings: useStudioEarnings,
  publisher: usePublisher,
};

const run = (hook: () => unknown) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(hook, { wrapper });
};

afterEach(() => {
  who.role = "owner";
  read.mockReset();
});

describe("publishing reads", () => {
  it.each(Object.entries(HOOKS))("never asks for %s as a member, whom the API refuses", async (_name, hook) => {
    who.role = "member";
    run(hook);
    await act(() => Promise.resolve());
    expect(read).not.toHaveBeenCalled();
  });

  it.each(Object.entries(HOOKS))("asks for %s as an owner or admin", async (_name, hook) => {
    who.role = "admin";
    read.mockResolvedValue({});
    run(hook);
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1));
  });
});
