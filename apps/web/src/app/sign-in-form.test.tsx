import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { SignInForm } from "./sign-in-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_AUTH_MOCK: true } }));
const session = { status: "signed-in" };
vi.mock("@/lib/auth/session", () => ({
  useSession: () => ({ ...session, signInWithGoogle: vi.fn(), signInWithEmail: vi.fn() }),
}));
const me: { isPending: boolean; isError: boolean; error?: unknown; data?: { role: string } } = {
  isPending: true,
  isError: false,
};
vi.mock("@/lib/queries/me", () => ({ useMe: () => me }));

const landWith = (search: string) => window.history.pushState({}, "", `/${search}`);
const answer = (role: string) => Object.assign(me, { isPending: false, isError: false, data: { role } });

describe("SignInForm after sign-in", () => {
  beforeEach(() => {
    push.mockClear();
    session.status = "signed-in";
    Object.assign(me, { isPending: true, isError: false, error: undefined, data: undefined });
  });
  afterEach(() => landWith(""));

  it("goes to a safe next before /v1/me has answered", async () => {
    landWith("?next=%2Fapp%2Fruns%2Frun_1042%3Fx%3D1");
    renderWithIntl(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/runs/run_1042?x=1"));
  });

  it("keeps an explicit next for a reviewer", async () => {
    landWith("?next=%2Fapp%2Fruns");
    answer("reviewer");
    renderWithIntl(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/runs"));
    expect(push).toHaveBeenCalledTimes(1);
  });

  it.each(["?next=%2F%2Fevil.com", "?next=https%3A%2F%2Fx", "?next=%2F%5Cevil.com", ""])(
    "goes to /app when next is %s",
    async (search) => {
      landWith(search);
      answer("owner");
      renderWithIntl(<SignInForm />);
      await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    },
  );

  it("sends a reviewer to the reviewer portal", async () => {
    answer("reviewer");
    renderWithIntl(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/work"));
  });

  it("waits for /v1/me when there is no next, then goes once", async () => {
    const { rerender } = renderWithIntl(<SignInForm />);
    await new Promise((r) => setTimeout(r, 0));
    expect(push).not.toHaveBeenCalled();
    answer("member");
    rerender(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    rerender(<SignInForm />);
    expect(push).toHaveBeenCalledTimes(1);
  });

  it("falls back to /app when /v1/me failed", async () => {
    Object.assign(me, { isPending: false, isError: true });
    renderWithIntl(<SignInForm />);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
  });

  it("keeps the form off while a signed-in visitor is being sent on", () => {
    renderWithIntl(<SignInForm />);
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
  });

  it("does not go anywhere on a 401 from /v1/me, and leaves the form usable", async () => {
    Object.assign(me, { isPending: false, isError: true, error: new ApiError(401, "UNAUTHENTICATED", "Unauthorized") });
    renderWithIntl(<SignInForm />);
    await new Promise((r) => setTimeout(r, 0));
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });
});

describe("SignInForm fields", () => {
  beforeEach(() => {
    session.status = "signed-out";
  });

  it("labels the fields, hints where the password comes from and can show it", async () => {
    renderWithIntl(<SignInForm />);
    const email = screen.getByRole("textbox", { name: "Email" });
    expect(email).toHaveAttribute("autocomplete", "username");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
    expect(password).toHaveAccessibleDescription("Sent to you with the demo login.");

    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(password).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    // The name follows the visible word, so it always says what the button does now.
    expect(toggle).toHaveTextContent("Hide");
    expect(toggle).toHaveAccessibleName("Hide password");
  });

  it("splits the note into a member line and a reviewer line", () => {
    renderWithIntl(<SignInForm />);
    expect(
      screen.getByText("Signing in with Google joins you to Harbor & Pine Supply Co. as a member."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Reviewers: after signing in, open the reviewer portal from the menu."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/paying/)).not.toBeInTheDocument();
  });
});
