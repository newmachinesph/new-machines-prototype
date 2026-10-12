import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_AUTH_MOCK: true, NEXT_PUBLIC_API_URL: "http://localhost:8100" } }));

import { handleUnauthorized } from "@/lib/api/client";
import { Guard } from "./guard";
import { SessionProvider, useSession } from "./session";

function setup() {
  const qc = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
  return { qc, wrapper };
}

beforeEach(() => {
  sessionStorage.clear();
  replace.mockClear();
});

describe("SessionProvider in mock mode", () => {
  it("starts signed out and reaches signed in after an email sign-in", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("signed-out"));
    expect(result.current.user).toBeNull();
    await act(() => result.current.signInWithEmail("a@b.co", "pw"));
    expect(result.current.status).toBe("signed-in");
    expect(result.current.user?.uid).toBe("user_demo");
  });

  it("signs out and clears the query cache", async () => {
    const { qc, wrapper } = setup();
    qc.setQueryData(["x"], 1);
    const { result } = renderHook(() => useSession(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("signed-out"));
    await act(() => result.current.signInWithGoogle());
    await act(() => result.current.signOut());
    expect(result.current.status).toBe("signed-out");
    expect(qc.getQueryData(["x"])).toBeUndefined();
  });
});

describe("Guard", () => {
  it("redirects to the landing page and hides children when signed out", async () => {
    const { wrapper } = setup();
    render(<Guard>secret</Guard>, { wrapper });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("keeps the deep link as a safe next for after sign-in", async () => {
    window.history.pushState({}, "", "/app/runs/run_1042?x=1");
    try {
      const { wrapper } = setup();
      render(<Guard>secret</Guard>, { wrapper });
      await waitFor(() => expect(replace).toHaveBeenCalledWith("/?next=%2Fapp%2Fruns%2Frun_1042%3Fx%3D1"));
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  it("renders children when signed in", async () => {
    sessionStorage.setItem("nm-mock-session", "1");
    const { wrapper } = setup();
    render(<Guard>secret</Guard>, { wrapper });
    expect(await screen.findByText("secret")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("a 401 from the API", () => {
  it("signs out, clears the cache, then redirects once even for a burst", async () => {
    const { qc, wrapper } = setup();
    qc.setQueryData(["x"], 1);
    const { result } = renderHook(() => useSession(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("signed-out"));
    await act(() => result.current.signInWithEmail("a@b.co", "pw"));
    expect(result.current.status).toBe("signed-in");
    await act(async () => {
      await Promise.all([handleUnauthorized(), handleUnauthorized(), handleUnauthorized()]);
    });
    expect(result.current.status).toBe("signed-out");
    expect(sessionStorage.getItem("nm-mock-session")).toBeNull();
    expect(qc.getQueryData(["x"])).toBeUndefined();
    expect(replace).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/");
  });
});
