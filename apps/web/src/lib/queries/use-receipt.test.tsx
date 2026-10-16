import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunStatus } from "@/lib/types";
import { useReceipt } from "./runs";

const fetchReceipt = vi.hoisted(() => vi.fn());
const workspace = vi.hoisted(() => ({ live: true }));
vi.mock("./me", async (orig) => ({ ...(await orig<object>()), useIsLive: () => workspace.live }));
vi.mock("@/lib/api/gen/@tanstack/react-query.gen", async (orig) => ({
  ...(await orig<object>()),
  getWorkflowRunReceiptOptions: (o: { path: { run_id: string } }) => ({
    queryKey: ["receipt", o.path.run_id],
    queryFn: fetchReceipt,
  }),
}));

const setup = (initial: RunStatus) => {
  const qc = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(({ status }) => useReceipt("run_9", status), { wrapper, initialProps: { status: initial } });
};

afterEach(() => {
  workspace.live = true;
  vi.useRealTimers();
  fetchReceipt.mockReset();
});

describe("useReceipt", () => {
  it("never asks for a receipt in the demo workspace, whose fixture runs have none", async () => {
    workspace.live = false;
    const { result } = setup("COMPLETED");
    await act(() => Promise.resolve());
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(fetchReceipt).not.toHaveBeenCalled();
  });

  it("fetches the receipt once more when the run's status changes", async () => {
    fetchReceipt.mockResolvedValue({ entries: 3 });
    const { rerender } = setup("RUNNING");
    await waitFor(() => expect(fetchReceipt).toHaveBeenCalledTimes(1));
    rerender({ status: "COMPLETED" });
    await waitFor(() => expect(fetchReceipt).toHaveBeenCalledTimes(2));
  });

  it("polls every 2 s while the run is active and the receipt exists", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchReceipt.mockResolvedValue({ entries: 3 });
    setup("RUNNING");
    await waitFor(() => expect(fetchReceipt).toHaveBeenCalledTimes(1));
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(fetchReceipt).toHaveBeenCalledTimes(2);
  });

  it("does not keep polling a run with no receipt (404)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fetchReceipt.mockRejectedValue(new Error("404"));
    setup("RUNNING");
    await waitFor(() => expect(fetchReceipt).toHaveBeenCalledTimes(1));
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(fetchReceipt).toHaveBeenCalledTimes(1);
  });
});
