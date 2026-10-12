import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { SignInForm } from "./sign-in-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_AUTH_MOCK: true } }));
vi.mock("@/lib/auth/session", () => ({
  useSession: () => ({ status: "signed-in", signInWithGoogle: vi.fn(), signInWithEmail: vi.fn() }),
}));

const landWith = (search: string) => window.history.pushState({}, "", `/${search}`);

describe("SignInForm after sign-in", () => {
  beforeEach(() => push.mockClear());
  afterEach(() => landWith(""));

  it("goes to a safe next", async () => {
    landWith("?next=%2Ftenants%2Forg_hp01%3Fx%3D1");
    render(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/tenants/org_hp01?x=1"));
  });

  it.each(["?next=%2F%2Fevil.com", "?next=https%3A%2F%2Fx", "?next=%2F%5Cevil.com", ""])(
    "goes to /command when next is %s",
    async (search) => {
      landWith(search);
      render(<SignInForm />);
      await waitFor(() => expect(push).toHaveBeenCalledWith("/command"));
    },
  );
});
