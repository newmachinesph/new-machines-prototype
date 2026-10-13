import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ConnectionList } from "./connection-list";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const data = vi.hoisted(() => ({ demo: false, conns: [] as unknown[] }));
const connect = vi.hoisted(() => vi.fn());

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo }));
vi.mock("@/lib/queries/org", () => ({ useConnections: () => ok(data.conns) }));
vi.mock("@/lib/queries/workspace", () => ({
  useConnectApp: () => ({ mutate: connect, isPending: false }),
  useDisconnect: () => ({ mutate: vi.fn() }),
  useRevokeGrant: () => ({ mutate: vi.fn() }),
}));

const live = (app: string, key: string, status: string, mode: "sandbox" | "composio" = "sandbox") => ({
  app,
  key,
  status,
  mode,
  provider: mode === "sandbox" ? "Mock" : "Composio",
  account: status === "sandbox" ? "Sandbox data" : "",
  oauthScopes: [],
  grants:
    status === "sandbox"
      ? [{ install: "Order & Payment Reconciliation", capability: "payment.read", access: "read" }]
      : [],
});

const card = (app: string) => screen.getByRole("heading", { name: new RegExp(`^${app}`) }).closest("section")!;

describe("ConnectionList in a live workspace", () => {
  beforeEach(() => {
    data.demo = false;
    connect.mockReset();
    data.conns = [live("Shopify", "shopify", "not_connected"), live("Stripe", "stripe", "sandbox")];
  });

  it("offers a sandbox connection for an app that is not connected, with no Simulated tag yet", async () => {
    renderWithIntl(<ConnectionList />);
    const shopify = card("Shopify");
    expect(within(shopify).getByText("Not connected")).toBeInTheDocument();
    expect(within(shopify).queryByText("Simulated")).not.toBeInTheDocument();
    await userEvent.click(within(shopify).getByRole("button", { name: "Connect Shopify (sandbox)" }));
    expect(connect).toHaveBeenCalledWith({ path: { app_name: "shopify" } }, expect.anything());
  });

  it("moves focus to the app's Disconnect control once it connects", async () => {
    const { rerender } = renderWithIntl(<ConnectionList />);
    connect.mockImplementation((_vars: unknown, opts: { onSuccess: () => void }) => {
      data.conns = [live("Shopify", "shopify", "sandbox"), live("Stripe", "stripe", "sandbox")];
      opts.onSuccess();
    });
    await userEvent.click(screen.getByRole("button", { name: "Connect Shopify (sandbox)" }));
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Shopify")).getByRole("button", { name: "Disconnect Shopify" })).toHaveFocus(),
    );
  });

  it("shows the Simulated tag by the sandbox note only once an app is simulated", () => {
    data.conns = [live("Shopify", "shopify", "not_connected")];
    renderWithIntl(<ConnectionList />);
    expect(screen.getByText(/sandbox data until live connections arrive/)).toBeInTheDocument();
    expect(screen.queryByText("Simulated")).not.toBeInTheDocument();
  });

  it("tags a connected sandbox app Simulated and keeps disconnect and revoke", () => {
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Simulated")).toBeInTheDocument();
    expect(within(stripe).getByText("Sandbox data")).toBeInTheDocument();
    expect(within(stripe).getByRole("button", { name: "Disconnect Stripe" })).toBeInTheDocument();
    expect(within(stripe).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });

  it("explains in one line that sandbox data is used until live connections arrive", () => {
    renderWithIntl(<ConnectionList />);
    expect(
      screen.getByText(
        "Apps use sandbox data until live connections arrive. Nothing is read from or written to your real accounts.",
      ),
    ).toBeInTheDocument();
  });

  it("asks the API to connect when live connections are configured, without a sandbox label", async () => {
    data.conns = [live("Shopify", "shopify", "not_connected", "composio")];
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Shopify" }));
    expect(connect).toHaveBeenCalled();
    expect(screen.queryByText(/sandbox data until/)).not.toBeInTheDocument();
  });

  it("links an empty list to the marketplace", () => {
    data.conns = [];
    renderWithIntl(<ConnectionList />);
    expect(
      screen.getByText("No apps yet. Hire a pack and the apps it needs appear here, ready to connect."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse the marketplace" })).toHaveAttribute("href", "/app/marketplace");
  });

  it("shows the sandbox action in Japanese", () => {
    renderWithIntl(<ConnectionList />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "Shopifyを接続（サンドボックス）" })).toBeInTheDocument();
  });
});

describe("ConnectionList in the demo workspace", () => {
  it("keeps the explanatory connect dialog for apps the demo cannot connect", async () => {
    data.demo = true;
    data.conns = [
      { app: "Slack", status: "not_connected", provider: "Composio", account: "", oauthScopes: [], grants: [] },
    ];
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
    expect(connect).not.toHaveBeenCalled();
    expect(await screen.findByText(/This demo workspace cannot connect real accounts/)).toBeInTheDocument();
  });
});
