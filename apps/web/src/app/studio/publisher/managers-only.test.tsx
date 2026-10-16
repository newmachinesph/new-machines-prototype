import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ManagersOnly } from "./managers-only";

const who = vi.hoisted(() => ({ role: "owner" as string | undefined }));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => ({ isPending: false, isError: false, data: who.role ? { role: who.role } : undefined }),
}));

describe("ManagersOnly", () => {
  beforeEach(() => {
    who.role = "owner";
  });

  it.each(["owner", "admin"])("shows publishing to an %s", (role) => {
    who.role = role;
    renderWithIntl(<ManagersOnly>listings</ManagersOnly>);
    expect(screen.getByText("listings")).toBeInTheDocument();
  });

  it("tells a member that only owners and admins can see publishing, with a way back to the Studio", () => {
    who.role = "member";
    renderWithIntl(<ManagersOnly>listings</ManagersOnly>);
    expect(screen.queryByText("listings")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Publisher" })).toBeInTheDocument();
    expect(screen.getByText("Only owners and admins can see publishing")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the Studio" })).toHaveAttribute("href", "/studio");
  });

  it("says the same in Japanese", () => {
    who.role = "member";
    renderWithIntl(<ManagersOnly>listings</ManagersOnly>, { locale: "ja" });
    expect(screen.getByText("公開の情報を見られるのはオーナーと管理者だけです")).toBeInTheDocument();
  });
});
