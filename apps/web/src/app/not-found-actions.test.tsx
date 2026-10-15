import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { NotFoundActions } from "./not-found-actions";

const session = { status: "loading" };
vi.mock("@/lib/auth/session", () => ({ useSession: () => session }));

describe("NotFoundActions", () => {
  it("offers sign-in to a visitor", () => {
    session.status = "signed-out";
    renderWithIntl(<NotFoundActions />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: "Go to overview" })).not.toBeInTheDocument();
  });

  it("offers the workspace to a member", () => {
    session.status = "signed-in";
    renderWithIntl(<NotFoundActions />);
    expect(screen.getByRole("link", { name: "Go to overview" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "See all runs" })).toHaveAttribute("href", "/app/runs");
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("shows nothing until the session is known", () => {
    session.status = "loading";
    renderWithIntl(<NotFoundActions />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
