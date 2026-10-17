import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { SignInForm } from "./sign-in-form";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("@/lib/env", () => ({ env: { NEXT_PUBLIC_AUTH_MOCK: true } }));
const session = {
  status: "signed-in",
  signInWithGoogle: vi.fn(),
  signInWithEmail: vi.fn(),
  createAccountWithEmail: vi.fn(),
};
vi.mock("@/lib/auth/session", () => ({ useSession: () => session }));
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
    expect(screen.getByRole("button", { name: "Create an account" })).toBeDisabled();
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

  it("says under each empty field what is missing, and clears it once typed in", async () => {
    renderWithIntl(<SignInForm />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const email = screen.getByRole("textbox", { name: "Email" });
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("Enter your email.");
    expect(email).toHaveFocus();
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAccessibleDescription("Enter your password. Sent to you with the demo login.");
    await userEvent.type(email, "a@b.co");
    expect(email).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("Enter your email.")).toBeNull();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
  });

  it("splits the note into a member line and a reviewer line", () => {
    renderWithIntl(<SignInForm />);
    expect(
      screen.getByText("Signing in with Google opens your own workspace, or the one you were invited to."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Reviewers: after signing in, open the reviewer portal from the menu."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/paying/)).not.toBeInTheDocument();
  });
});

describe("SignInForm creating an account", () => {
  const openCreate = async () => {
    renderWithIntl(<SignInForm />);
    await userEvent.click(screen.getByRole("button", { name: "Create an account" }));
  };
  const fill = async (name: string, email: string, password: string) => {
    if (name) await userEvent.type(screen.getByRole("textbox", { name: "Name" }), name);
    if (email) await userEvent.type(screen.getByRole("textbox", { name: "Email" }), email);
    if (password) await userEvent.type(screen.getByLabelText("Password"), password);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
  };

  beforeEach(() => {
    session.status = "signed-out";
    session.createAccountWithEmail.mockReset().mockResolvedValue(undefined);
    session.signInWithEmail.mockReset();
    Object.assign(me, { isPending: true, isError: false, error: undefined, data: undefined });
  });

  it("switches to the create form and back", async () => {
    await openCreate();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("autocomplete", "name");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("autocomplete", "new-password");
    expect(password).toHaveAccessibleDescription("At least 8 characters.");
    expect(screen.getByRole("button", { name: "Create account" })).toBeInTheDocument();
    expect(screen.getByText("or use your email")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create an account" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute("type", "submit");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.getByRole("button", { name: "Create an account" })).toBeInTheDocument();
  });

  it("asks for a name, a real email and a longer password before creating anything", async () => {
    await openCreate();
    await fill("", "nora", "short");
    const name = screen.getByRole("textbox", { name: "Name" });
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("Enter your name.");
    expect(name).toHaveFocus();
    const email = screen.getByRole("textbox", { name: "Email" });
    expect(email).toHaveAccessibleDescription("Enter a valid email address.");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAccessibleDescription("Use at least 8 characters. At least 8 characters.");
    expect(session.createAccountWithEmail).not.toHaveBeenCalled();

    await userEvent.type(name, "Nora");
    expect(name).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText("Enter your name.")).toBeNull();
  });

  it("creates the account with the trimmed name and email, then shows it is under way", async () => {
    let finish = () => {};
    session.createAccountWithEmail.mockReturnValue(new Promise<void>((r) => (finish = r)));
    await openCreate();
    await fill("  Nora Ito ", " nora@example.com ", "longenough1");
    expect(session.createAccountWithEmail).toHaveBeenCalledWith("Nora Ito", "nora@example.com", "longenough1");
    expect(session.signInWithEmail).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Creating your account…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    finish();
  });

  it.each([
    ["auth/email-already-in-use", "An account with that email already exists. Sign in instead."],
    ["auth/invalid-email", "That email address does not look right. Check it and try again."],
    ["auth/weak-password", "That password is too easy to guess. Choose a longer one."],
    ["auth/too-many-requests", "Too many attempts. Wait a minute and try again."],
    ["auth/network-request-failed", "Can't reach the sign-in service. Check your connection and try again."],
    ["auth/internal-error", "Your account could not be created. Try again."],
  ])("explains %s and gives the form back", async (code, message) => {
    session.createAccountWithEmail.mockRejectedValue({ code });
    await openCreate();
    await fill("Nora", "nora@example.com", "longenough1");
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Create account" })).toBeEnabled();
  });

  it("says that invitations need Google, and drops the note when switching back", async () => {
    await openCreate();
    const note = "To accept an invitation to another workspace, sign in with Google instead.";
    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.queryByText(/Reviewers:/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.queryByText(note)).toBeNull();
    expect(screen.getByText(/Reviewers:/)).toBeInTheDocument();
  });
});
