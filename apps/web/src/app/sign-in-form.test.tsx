import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
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
    landWith("?next=%2Fapp%2Fruns%2Frun_1042%3Fx%3D1");
    renderWithIntl(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/runs/run_1042?x=1"));
  });

  it.each(["?next=%2F%2Fevil.com", "?next=https%3A%2F%2Fx", "?next=%2F%5Cevil.com", ""])(
    "goes to /app when next is %s",
    async (search) => {
      landWith(search);
      renderWithIntl(<SignInForm />);
      await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    },
  );
});
