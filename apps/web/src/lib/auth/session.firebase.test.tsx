import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The provider against the sign-in service itself (not mock mode), with the service replaced by a stand-in
// that behaves like Firebase does: creating an account signs it in at once, nameless.
type FakeUser = { uid: string; email: string | null; displayName: string | null; getIdToken: ReturnType<typeof vi.fn> };
const fb = vi.hoisted(() => ({
  auth: { currentUser: null as FakeUser | null },
  listener: null as ((u: FakeUser | null) => void) | null,
  createUserWithEmailAndPassword: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));
vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_AUTH_MOCK: false, NEXT_PUBLIC_API_URL: "http://localhost:8100" } }));
vi.mock("./firebase", () => ({ auth: fb.auth }));
vi.mock("firebase/auth", () => ({
  onIdTokenChanged: (_auth: unknown, next: (u: FakeUser | null) => void) => {
    fb.listener = next;
    return () => {};
  },
  createUserWithEmailAndPassword: (...args: unknown[]) => fb.createUserWithEmailAndPassword(...args),
  updateProfile: (...args: unknown[]) => fb.updateProfile(...args),
}));

import { SessionProvider, useSession } from "./session";

function setup() {
  const qc = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  );
  return renderHook(() => useSession(), { wrapper });
}

/** A user the way the service returns it on creation: signed in, with a token but no name yet. */
function createdUser(email: string): FakeUser {
  const user: FakeUser = { uid: "user_new", email, displayName: null, getIdToken: vi.fn() };
  fb.createUserWithEmailAndPassword.mockImplementation(async () => {
    fb.auth.currentUser = user;
    fb.listener?.(user);
    return { user };
  });
  fb.updateProfile.mockImplementation(async (u: FakeUser, { displayName }: { displayName: string }) => {
    u.displayName = displayName;
  });
  return user;
}

beforeEach(() => {
  fb.auth.currentUser = null;
  fb.listener = null;
  fb.createUserWithEmailAndPassword.mockReset();
  fb.updateProfile.mockReset();
});

describe("SessionProvider creating an account", () => {
  it("creates the user, names it, refreshes the token, and only then is signed in", async () => {
    const user = createdUser("nora@example.com");
    let refreshed = () => {};
    user.getIdToken.mockReturnValue(new Promise<string>((r) => (refreshed = () => r("token"))));
    const { result } = setup();
    await waitFor(() => expect(fb.listener).not.toBeNull());
    act(() => fb.listener?.(null));
    expect(result.current.status).toBe("signed-out");

    let done: Promise<void> | undefined;
    act(() => {
      done = result.current.createAccountWithEmail("Nora Ito", "nora@example.com", "longenough1");
    });
    await waitFor(() => expect(user.getIdToken).toHaveBeenCalledWith(true));
    // The service already reported the nameless user, but the session waits for the name to be on the token.
    expect(fb.createUserWithEmailAndPassword).toHaveBeenCalledWith(fb.auth, "nora@example.com", "longenough1");
    expect(fb.updateProfile).toHaveBeenCalledWith(user, { displayName: "Nora Ito" });
    expect(fb.updateProfile.mock.invocationCallOrder[0]).toBeLessThan(user.getIdToken.mock.invocationCallOrder[0]);
    expect(result.current.status).toBe("signed-out");

    await act(async () => {
      refreshed();
      await done;
    });
    expect(result.current.status).toBe("signed-in");
    expect(result.current.user).toEqual({ uid: "user_new", email: "nora@example.com", name: "Nora Ito" });
  });

  it("still signs in when the name could not be saved after the account was created", async () => {
    const user = createdUser("nora@example.com");
    fb.updateProfile.mockRejectedValue({ code: "auth/network-request-failed" });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = setup();
    await waitFor(() => expect(fb.listener).not.toBeNull());
    act(() => fb.listener?.(null));

    await act(() => result.current.createAccountWithEmail("Nora Ito", "nora@example.com", "longenough1"));
    expect(user.getIdToken).not.toHaveBeenCalled();
    expect(result.current.status).toBe("signed-in");
    expect(result.current.user).toEqual({ uid: "user_new", email: "nora@example.com", name: null });
    expect(warn).toHaveBeenCalledOnce();
    warn.mockRestore();
  });

  it("passes the service's error on and stays signed out", async () => {
    fb.createUserWithEmailAndPassword.mockRejectedValue({ code: "auth/email-already-in-use" });
    const { result } = setup();
    await waitFor(() => expect(fb.listener).not.toBeNull());
    act(() => fb.listener?.(null));

    await expect(
      act(() => result.current.createAccountWithEmail("Nora", "nora@example.com", "longenough1")),
    ).rejects.toEqual({ code: "auth/email-already-in-use" });
    expect(fb.updateProfile).not.toHaveBeenCalled();
    expect(result.current.status).toBe("signed-out");

    // The listener is live again afterwards.
    act(() => fb.listener?.({ uid: "u", email: "a@b.co", displayName: "A", getIdToken: vi.fn() }));
    expect(result.current.status).toBe("signed-in");
  });
});
