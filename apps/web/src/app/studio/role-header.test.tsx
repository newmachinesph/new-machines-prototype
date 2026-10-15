import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { RoleHeader } from "./role-header";

const state = vi.hoisted(() => ({ me: { role: "owner" } as { role: string } | undefined }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: state.me }) }));

const EDIT = { title: "Edit agent", lede: "Saving makes a new version." };
const VIEW = { title: "Agent", lede: "Only an owner or admin can change it." };

describe("RoleHeader", () => {
  it("reads as editing for an owner or admin", () => {
    state.me = { role: "admin" };
    renderWithIntl(<RoleHeader edit={EDIT} view={VIEW} />);
    expect(screen.getByRole("heading", { name: "Edit agent" })).toBeInTheDocument();
    expect(screen.getByText("Saving makes a new version.")).toBeInTheDocument();
  });

  it("reads as viewing for a member, who cannot save", () => {
    state.me = { role: "member" };
    renderWithIntl(<RoleHeader edit={EDIT} view={VIEW} />);
    expect(screen.getByRole("heading", { name: "Agent" })).toBeInTheDocument();
    expect(screen.getByText("Only an owner or admin can change it.")).toBeInTheDocument();
    expect(screen.queryByText("Edit agent")).toBeNull();
  });

  it("reads as editing until the role is known, so the title does not change for builders", () => {
    state.me = undefined;
    renderWithIntl(<RoleHeader edit={EDIT} view={VIEW} />);
    expect(screen.getByRole("heading", { name: "Edit agent" })).toBeInTheDocument();
  });
});
