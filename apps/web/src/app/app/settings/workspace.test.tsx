import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PoliciesSection, WorkspaceSection, splitPolicyRef } from "./workspace";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const data = vi.hoisted(() => ({ policies: [] as unknown[], region: "asia-south1" }));

vi.mock("@/lib/queries/workspace", () => ({ usePolicies: () => ok(data.policies) }));
vi.mock("@/lib/queries/org", () => ({
  useOrg: () =>
    ok({
      id: "org_new",
      name: "Ana's workspace",
      short: "Ana's workspace",
      plan: "Trial",
      monthlyCap: { amountMinor: 25000, currency: "USD" },
      monthSpent: { amountMinor: 0, currency: "USD" },
      region: data.region,
    }),
}));

const policy = (ref: string, summary = "What this policy enforces.") => ({ ref, summary, updated: "Oct 15" });

describe("splitPolicyRef", () => {
  it("separates the name from the version, and keeps a ref without one whole", () => {
    expect(splitPolicyRef("tool_actions@1")).toEqual({ name: "tool_actions", version: "1" });
    expect(splitPolicyRef("custom")).toEqual({ name: "custom" });
  });
});

describe("PoliciesSection", () => {
  beforeEach(() => {
    data.policies = [
      policy("tool_actions@1"),
      policy("region@1", "Customer data is stored in Mumbai."),
      policy("data_retention@2"),
    ];
  });

  it("titles each policy in words with its version as separate text, never the raw ref", () => {
    renderWithIntl(<PoliciesSection />);
    expect(screen.getByRole("heading", { level: 3, name: "Tool actions Version 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Data region Version 1" })).toBeInTheDocument();
    expect(screen.queryByText(/@\d/)).not.toBeInTheDocument();
    expect(screen.getByText("Customer data is stored in Mumbai.")).toBeInTheDocument();
  });

  it("reads an unknown policy name as words", () => {
    renderWithIntl(<PoliciesSection />);
    expect(screen.getByRole("heading", { level: 3, name: "Data retention Version 2" })).toBeInTheDocument();
  });

  it("is translated", () => {
    renderWithIntl(<PoliciesSection />, { locale: "ja" });
    expect(screen.getByRole("heading", { level: 3, name: "ツールの操作 バージョン1" })).toBeInTheDocument();
  });
});

describe("WorkspaceSection", () => {
  it("names the place a known region code stands for, and shows an unknown code as is", () => {
    data.region = "asia-south1";
    const { unmount } = renderWithIntl(<WorkspaceSection />);
    expect(screen.getByText("Mumbai (asia-south1)")).toBeInTheDocument();
    unmount();
    data.region = "europe-west9";
    renderWithIntl(<WorkspaceSection />);
    expect(screen.getByText("europe-west9")).toBeInTheDocument();
  });

  it("names the region's place in Japanese too", () => {
    data.region = "asia-northeast1";
    renderWithIntl(<WorkspaceSection />, { locale: "ja" });
    expect(screen.getByText("東京（asia-northeast1）")).toBeInTheDocument();
  });
});
