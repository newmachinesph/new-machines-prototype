import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { UiProviders } from "./base";

let me: { data?: unknown; error?: unknown; isPending: boolean } = { isPending: true };
vi.mock("next/navigation", () => ({ usePathname: () => "/tenants/org_hp01" }));
vi.mock("@/lib/queries/ops", () => ({ useMe: () => me }));
vi.mock("@/lib/auth/session", () => ({
  useSession: () => ({ user: { email: "someone@example.com" }, signOut: vi.fn(async () => {}) }),
}));

import { locate, OpsShell } from "./ops-shell";

const renderShell = () =>
  render(
    <UiProviders>
      <OpsShell>
        <p>page body</p>
      </OpsShell>
    </UiProviders>,
  );

describe("OpsShell", () => {
  beforeEach(() => {
    me = { isPending: true };
    // jsdom has no matchMedia; the drawer listens for the window growing past lg.
    window.matchMedia = vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  });

  it("marks the current section and shows where you are", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Console" });
    expect(nav.querySelector('[aria-current="page"]')).toHaveTextContent("Tenants");
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("org_hp01");
    expect(
      screen.getByText((_, el) => el?.tagName === "SPAN" && el.textContent === "Demo environment"),
    ).toBeInTheDocument();
    expect(screen.queryByText("page body")).toBeNull();
  });

  it("renders the page only once the API confirms an operator", () => {
    me = { isPending: false, data: { userId: "ops_demo", email: "ops@newmachin.es", role: "owner" } };
    renderShell();
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("offers a retry instead of the page when the operator check fails for another reason", () => {
    me = { isPending: false, error: new ApiError(503, "AUTH_UNAVAILABLE", "Try again.") };
    renderShell();
    expect(screen.getByRole("alert")).toHaveTextContent("The API did not answer");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("page body")).toBeNull();
  });

  it("shows the operator's email and role", () => {
    me = { isPending: false, data: { userId: "ops_demo", email: "ops@newmachin.es", role: "owner" } };
    renderShell();
    expect(screen.getByText("ops@newmachin.es")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("replaces the page with a no-access panel when the API refuses the operator", () => {
    me = { isPending: false, error: new ApiError(403, "OPS_FORBIDDEN", "Not an operator.") };
    renderShell();
    expect(screen.getByRole("alert")).toHaveTextContent("someone@example.com is not on the ops allowlist");
    expect(screen.queryByText("page body")).toBeNull();
  });
});

describe("locate", () => {
  it("finds the nav entry and group for nested paths, and nothing for unknown ones", () => {
    expect(locate("/marketplace/shipping-exceptions")?.item.label).toBe("Marketplace");
    expect(locate("/audit")?.group.label).toBe("Platform");
    expect(locate("/commander")).toBeNull();
  });

  it("files the definition pages under Build, a schema key's slash included", () => {
    expect(locate("/definitions/schema/order-payment-reconciliation/input")?.item.label).toBe("Definitions");
    expect(locate("/agents")?.group.label).toBe("Build");
    expect(locate("/contracts")?.item.label).toBe("Work Contracts");
    expect(locate("/memory")?.item.label).toBe("Memory");
  });
});
