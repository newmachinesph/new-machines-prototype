import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ConnectionList } from "./connection-list";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const data = vi.hoisted(() => ({ demo: false, role: "owner", conns: [] as unknown[] }));
const connect = vi.hoisted(() => vi.fn());
const sync = vi.hoisted(() => vi.fn());
const disconnect = vi.hoisted(() => vi.fn());
const allow = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
const leaveFor = vi.hoisted(() => vi.fn());
const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => "/app/connections",
}));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));
vi.mock("@/lib/navigate", () => ({ leaveFor }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo, useMe: () => ({ data: { role: data.role } }) }));
vi.mock("@/lib/queries/org", () => ({ useConnections: () => ok(data.conns) }));
vi.mock("@/lib/queries/workspace", () => ({
  connectorKey: (c: { key?: string; app: string }) => c.key ?? c.app,
  findConnection: (conns: { key?: string; app: string }[] | undefined, key: string) =>
    key ? conns?.find((c) => (c.key ?? c.app) === key) : undefined,
  useConnectApp: () => ({ mutate: connect, isPending: false }),
  useSyncConnection: () => ({ mutate: sync, isPending: false }),
  useDisconnect: () => ({ mutate: disconnect }),
  useRevokeGrant: () => ({ mutate: vi.fn() }),
  useAllowGrant: () => ({ mutate: allow, isPending: false }),
}));

type Answer = { onSuccess: (c?: unknown) => void };
const answer = (mock: ReturnType<typeof vi.fn>, row: () => unknown) =>
  mock.mockImplementation((_vars: unknown, opts: Answer) => opts.onSuccess(row()));

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
  revoked: [],
});

const card = (app: string) => screen.getByRole("heading", { name: new RegExp(`^${app}`) }).closest("section")!;

beforeEach(() => {
  for (const m of [connect, sync, disconnect, allow, toast, leaveFor, nav.replace]) m.mockReset();
  leaveFor.mockReturnValue(true);
  nav.search = "";
  data.demo = false;
  data.role = "owner";
  data.conns = [live("Shopify", "shopify", "not_connected"), live("Stripe", "stripe", "sandbox")];
});

const ASK_ADMIN = "Ask an owner or admin to connect real accounts.";

describe("ConnectionList for a member of a live workspace", () => {
  beforeEach(() => {
    data.role = "member";
  });

  it("offers simulated data only for an app that is not connected, and says whom to ask", () => {
    renderWithIntl(<ConnectionList />);
    const shopify = card("Shopify");
    expect(within(shopify).queryByRole("button", { name: "Connect Shopify" })).not.toBeInTheDocument();
    expect(within(shopify).getByRole("button", { name: "Use simulated data for Shopify" })).toBeInTheDocument();
    expect(within(shopify).getByText(ASK_ADMIN)).toBeInTheDocument();
  });

  it("keeps Disconnect on a simulated app but not the switch to the real account, nor Revoke", () => {
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByRole("button", { name: "Disconnect Stripe" })).toBeInTheDocument();
    expect(
      within(stripe).queryByRole("button", { name: "Switch Stripe to your real account" }),
    ).not.toBeInTheDocument();
    expect(within(stripe).queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(within(stripe).getByText(ASK_ADMIN)).toBeInTheDocument();
  });

  it("shows a real account without Disconnect, Revoke or Allow again", () => {
    data.conns = [
      {
        ...live("Stripe", "stripe", "connected", "composio"),
        grants: [{ install: "Order & Payment Reconciliation", capability: "payment.read", access: "read" }],
        revoked: [{ install: "Order & Payment Reconciliation", capability: "payment.write" }],
      },
    ];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).queryByRole("button", { name: "Disconnect Stripe" })).not.toBeInTheDocument();
    expect(within(stripe).queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(within(stripe).queryByRole("button", { name: /Allow again/ })).not.toBeInTheDocument();
    expect(within(stripe).getByText("Revoked")).toBeInTheDocument();
    expect(within(stripe).getByText(ASK_ADMIN)).toBeInTheDocument();
  });

  it("lets a pending sign-in be finished but not cancelled", () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByRole("button", { name: "Finish connecting Stripe" })).toBeInTheDocument();
    expect(within(stripe).queryByRole("button", { name: "Cancel connecting Stripe" })).not.toBeInTheDocument();
    expect(within(stripe).getByText(ASK_ADMIN)).toBeInTheDocument();
  });

  it("says a sign-in is still pending instead of starting a fresh one", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    answer(sync, () => live("Stripe", "stripe", "pending", "composio"));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Stripe")).getByRole("button", { name: "Finish connecting Stripe" }));
    expect(sync).toHaveBeenCalledTimes(1);
    expect(connect).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(
      "Signing in to Stripe is not finished",
      "Finish signing in on the Stripe page, then come back here.",
      "blocked",
    );
  });

  it("keeps every control in the demo workspace, whatever the role", () => {
    data.demo = true;
    renderWithIntl(<ConnectionList />);
    expect(within(card("Stripe")).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(screen.queryByText(ASK_ADMIN)).not.toBeInTheDocument();
  });
});

describe("ConnectionList in a live workspace", () => {
  it("offers the real account first and simulated data for an app that is not connected", async () => {
    renderWithIntl(<ConnectionList />);
    const shopify = card("Shopify");
    expect(within(shopify).getByText("Not connected")).toBeInTheDocument();
    expect(within(shopify).queryByText("Simulated")).not.toBeInTheDocument();
    const buttons = within(shopify).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([
      "Connect Shopify",
      "Use simulated data for Shopify",
    ]);
  });

  it("sends the browser to the app's sign-in page for the real account", async () => {
    answer(connect, () => ({
      ...live("Shopify", "shopify", "pending", "composio"),
      redirectUrl: "https://connect.example/x",
    }));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Shopify")).getByRole("button", { name: "Connect Shopify" }));
    expect(connect).toHaveBeenCalledWith({ path: { app_name: "shopify" }, body: { mode: "live" } }, expect.anything());
    expect(leaveFor).toHaveBeenCalledWith("https://connect.example/x");
    expect(toast).not.toHaveBeenCalled();
  });

  it("treats a real account that is already connected as connected, without leaving", async () => {
    answer(connect, () => live("Shopify", "shopify", "connected", "composio"));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Shopify")).getByRole("button", { name: "Connect Shopify" }));
    expect(leaveFor).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(
      "Shopify connected",
      "Packs you added now use your real Shopify account, within the access you grant them.",
    );
  });

  it("connects simulated data and moves focus to the app's Disconnect control", async () => {
    const { rerender } = renderWithIntl(<ConnectionList />);
    connect.mockImplementation((_vars: unknown, opts: Answer) => {
      data.conns = [live("Shopify", "shopify", "sandbox"), live("Stripe", "stripe", "sandbox")];
      opts.onSuccess(live("Shopify", "shopify", "sandbox"));
    });
    await userEvent.click(screen.getByRole("button", { name: "Use simulated data for Shopify" }));
    expect(connect).toHaveBeenCalledWith(
      { path: { app_name: "shopify" }, body: { mode: "sandbox" } },
      expect.anything(),
    );
    expect(toast).toHaveBeenCalledWith(
      "Shopify connected",
      "It uses simulated data. Nothing reaches your real account.",
      "sim",
    );
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Shopify")).getByRole("button", { name: "Disconnect Shopify" })).toHaveFocus(),
    );
  });

  it("shows the sandbox note with the Simulated tag only once an app is simulated", () => {
    data.conns = [live("Shopify", "shopify", "not_connected")];
    const { unmount } = renderWithIntl(<ConnectionList />);
    expect(screen.queryByText(/Simulated apps use sandbox data/)).not.toBeInTheDocument();
    unmount();
    data.conns = [live("Stripe", "stripe", "sandbox")];
    renderWithIntl(<ConnectionList />);
    expect(
      screen.getByText("Simulated apps use sandbox data. Nothing is read from or written to your real accounts."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
  });

  it("tags a connected sandbox app Simulated and keeps disconnect and revoke", () => {
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Simulated")).toBeInTheDocument();
    expect(within(stripe).getByText("Sandbox data")).toBeInTheDocument();
    expect(within(stripe).getByRole("button", { name: "Disconnect Stripe" })).toBeInTheDocument();
    expect(within(stripe).getByRole("button", { name: "Revoke" })).toBeInTheDocument();
  });

  it("finishes a pending sign-in, and starts a fresh one while it is still pending", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    answer(sync, () => live("Stripe", "stripe", "pending", "composio"));
    answer(connect, () => ({ ...live("Stripe", "stripe", "pending", "composio"), redirectUrl: "https://c.example/y" }));
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Finishing sign-in")).toBeInTheDocument();
    expect(within(stripe).getByText(/Signing in to Stripe is not finished/)).toBeInTheDocument();
    await userEvent.click(within(stripe).getByRole("button", { name: "Finish connecting Stripe" }));
    expect(sync).toHaveBeenCalledWith({ path: { app_name: "stripe" } }, expect.anything());
    expect(connect).toHaveBeenCalledWith({ path: { app_name: "stripe" }, body: { mode: "live" } }, expect.anything());
    expect(leaveFor).toHaveBeenCalledWith("https://c.example/y");
  });

  it("says so when the finished sign-in connected the real account", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    answer(sync, () => ({ ...live("Stripe", "stripe", "connected", "composio"), account: "acct_1" }));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Finish connecting Stripe" }));
    expect(toast).toHaveBeenCalledWith(
      "Stripe connected",
      "Packs you added now use your real Stripe account, within the access you grant them.",
    );
    expect(connect).not.toHaveBeenCalled();
  });

  it("says the app uses simulated data, not that it connected, when it was switched meanwhile", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    sync.mockImplementation((_vars: unknown, opts: Answer) => {
      data.conns = [live("Stripe", "stripe", "sandbox")];
      opts.onSuccess(live("Stripe", "stripe", "sandbox"));
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Finish connecting Stripe" }));
    expect(toast).toHaveBeenCalledWith(
      "Stripe uses simulated data",
      "It was switched to simulated data while you were signing in. Nothing reaches your real account.",
      "sim",
    );
    expect(toast).not.toHaveBeenCalledWith("Stripe connected", expect.anything(), expect.anything());
    expect(connect).not.toHaveBeenCalled();
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Stripe")).getByRole("button", { name: "Disconnect Stripe" })).toHaveFocus(),
    );
  });

  it("does not pretend success when the sign-in did not finish, and moves focus to Connect", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    sync.mockImplementation((_vars: unknown, opts: Answer) => {
      data.conns = [live("Stripe", "stripe", "not_connected")];
      opts.onSuccess(live("Stripe", "stripe", "not_connected"));
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Finish connecting Stripe" }));
    expect(toast).toHaveBeenCalledWith(
      "Could not connect Stripe",
      "The sign-in did not finish. Try again, or use simulated data.",
      "blocked",
    );
    expect(connect).not.toHaveBeenCalled();
    expect(leaveFor).not.toHaveBeenCalled();
    rerender(<ConnectionList />);
    await waitFor(() => expect(within(card("Stripe")).getByRole("button", { name: "Connect Stripe" })).toHaveFocus());
  });

  it("says the sign-in is not finished when the real account answers without a sign-in page", async () => {
    connect.mockImplementation((_vars: unknown, opts: Answer) => {
      data.conns = [live("Shopify", "shopify", "pending", "composio"), live("Stripe", "stripe", "sandbox")];
      opts.onSuccess(live("Shopify", "shopify", "pending", "composio"));
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Shopify")).getByRole("button", { name: "Connect Shopify" }));
    expect(leaveFor).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(
      "Signing in to Shopify is not finished",
      "Finish signing in on the Shopify page, then come back here.",
      "blocked",
    );
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Shopify")).getByRole("button", { name: "Finish connecting Shopify" })).toHaveFocus(),
    );
  });

  it("stays here and says so when the sign-in page is not a secure web address", async () => {
    leaveFor.mockReturnValue(false);
    answer(connect, () => ({ ...live("Shopify", "shopify", "pending", "composio"), redirectUrl: "javascript:1" }));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Shopify")).getByRole("button", { name: "Connect Shopify" }));
    expect(leaveFor).toHaveBeenCalledWith("javascript:1");
    expect(toast).toHaveBeenCalledWith(
      "Could not connect Shopify",
      "The app's sign-in link was not a secure web address, so the browser stayed here.",
      "blocked",
    );
  });

  it("cancels a pending sign-in by disconnecting, from a control that is not the card's Disconnect", async () => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    renderWithIntl(<ConnectionList />);
    const cancel = screen.getByRole("button", { name: "Cancel connecting Stripe" });
    expect(cancel).not.toHaveAttribute("data-disconnect");
    expect(cancel).toHaveAttribute("data-cancel", "Stripe");
    await userEvent.click(cancel);
    expect(disconnect).toHaveBeenCalledWith({ path: { app_name: "stripe" } }, expect.anything());
  });

  it("offers a simulated app the switch to its real account, after saying what it means", async () => {
    renderWithIntl(<ConnectionList />);
    await userEvent.click(within(card("Stripe")).getByRole("button", { name: "Switch Stripe to your real account" }));
    expect(connect).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog", { name: "Switch Stripe to your real account?" });
    expect(
      within(dialog).getByText(
        "Runs that need Stripe can't use it until the sign-in finishes; runs already going stop at their next Stripe step. Simulated data stops being used.",
      ),
    ).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch to real account" }));
    expect(connect).toHaveBeenCalledWith({ path: { app_name: "stripe" }, body: { mode: "live" } }, expect.anything());
  });

  it("shows a real account without the Simulated tag", () => {
    data.conns = [live("Stripe", "stripe", "connected", "composio")];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).queryByText("Simulated")).not.toBeInTheDocument();
    expect(within(stripe).getByText("Your Stripe account")).toBeInTheDocument();
    expect(within(stripe).getByText("Via your own account")).toBeInTheDocument();
    expect(within(stripe).queryByRole("button", { name: /Switch Stripe/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Simulated apps use sandbox data/)).not.toBeInTheDocument();
  });

  it("asks a real account that expired to sign in again", async () => {
    data.conns = [live("Stripe", "stripe", "needs_reauth", "composio")];
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in to Stripe again" }));
    expect(connect).toHaveBeenCalledWith({ path: { app_name: "stripe" }, body: { mode: "live" } }, expect.anything());
  });

  it("says when a real account's sign-in could not be removed", async () => {
    data.conns = [live("Stripe", "stripe", "connected", "composio")];
    answer(disconnect, () => ({ ...live("Stripe", "stripe", "not_connected"), notice: "sign_in_not_removed" }));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Disconnect Stripe" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Disconnect Stripe" }),
    );
    expect(toast).toHaveBeenCalledWith(
      "Stripe disconnected",
      "Stripe is disconnected here, but its sign-in could not be removed from the connection service yet. It is removed the next time you connect Stripe.",
      "blocked",
    );
  });

  it("leaves the org's own MCP servers to their own section", () => {
    data.conns = [
      live("Stripe", "stripe", "sandbox"),
      { ...live("Acme CRM", "org-a1--acme-crm", "connected", "composio"), provider: "MCP", mode: "mcp" },
    ];
    renderWithIntl(<ConnectionList />);
    expect(screen.getByRole("heading", { name: /^Stripe/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Acme CRM/ })).not.toBeInTheDocument();
  });

  it("lists a revoked grant and allows it again", async () => {
    const revoked = { install: "Order & Payment Reconciliation", capability: "payment.refund" };
    data.conns = [{ ...live("Stripe", "stripe", "sandbox"), revoked: [revoked] }];
    const row = live("Stripe", "stripe", "sandbox");
    answer(allow, () => ({ ...row, grants: [...row.grants, { ...revoked, access: "write" }] }));
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Revoked")).toBeInTheDocument();
    expect(within(stripe).getByText("Refund payment")).toBeInTheDocument();
    await userEvent.click(
      within(stripe).getByRole("button", {
        name: "Allow Order & Payment Reconciliation “Refund payment” on Stripe again",
      }),
    );
    expect(allow).toHaveBeenCalledWith({ query: { app: "stripe", ...revoked } }, expect.anything());
    expect(toast).toHaveBeenCalledWith(
      "Access allowed again",
      "Order & Payment Reconciliation has “Refund payment” on Stripe again.",
    );
  });

  it("says nothing was added when no pack uses the allowed capability any more", async () => {
    const revoked = { install: "Order & Payment Reconciliation", capability: "payment.refund" };
    data.conns = [{ ...live("Stripe", "stripe", "sandbox"), revoked: [revoked] }];
    answer(allow, () => live("Stripe", "stripe", "sandbox"));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: /Allow Order & Payment Reconciliation/ }));
    expect(toast).toHaveBeenCalledWith(
      "Nothing added",
      "Order & Payment Reconciliation no longer uses “Refund payment” on Stripe, so nothing was added. The revocation is forgotten.",
    );
    expect(toast).not.toHaveBeenCalledWith("Access allowed again", expect.anything());
  });

  it("says when the grant is back but a policy denies it", async () => {
    const revoked = { install: "Order & Payment Reconciliation", capability: "payment.refund" };
    data.conns = [{ ...live("Stripe", "stripe", "sandbox"), revoked: [revoked] }];
    const row = live("Stripe", "stripe", "sandbox");
    answer(allow, () => ({ ...row, grants: [...row.grants, { ...revoked, access: "denied" }] }));
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: /Allow Order & Payment Reconciliation/ }));
    expect(toast).toHaveBeenCalledWith(
      "Allowed again, but policy denies it",
      "Order & Payment Reconciliation has “Refund payment” on Stripe again, but a policy denies the call. Change the policy to let it through.",
      "blocked",
    );
    expect(toast).not.toHaveBeenCalledWith("Nothing added", expect.anything());
  });

  it("names each grant in words and makes the destructive actions real buttons that ask first", async () => {
    data.conns = [
      {
        ...live("Stripe", "stripe", "sandbox"),
        grants: [
          { install: "Order & Payment Reconciliation", capability: "payment.read", access: "read" },
          { install: "Order & Payment Reconciliation", capability: "sheets.write", access: "write" },
        ],
      },
    ];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Read payment")).toBeInTheDocument();
    expect(within(stripe).getByText("Write sheets")).toBeInTheDocument();
    expect(within(stripe).queryByText(/payment\.read|sheets\.write/)).toBeNull();
    const disconnect = within(stripe).getByRole("button", { name: "Disconnect Stripe" });
    const [revoke] = within(stripe).getAllByRole("button", { name: "Revoke" });
    for (const b of [disconnect, revoke]) {
      expect(b.tagName).toBe("BUTTON");
      expect(b).toHaveClass("text-blocked");
    }
    await userEvent.click(revoke);
    const dialog = await screen.findByRole("alertdialog", { name: "Revoke this access?" });
    expect(
      within(dialog).getByText(
        "Order & Payment Reconciliation loses “Read payment” on Stripe. You can allow it again from this page.",
      ),
    ).toBeInTheDocument();
  });

  it("maps known resources and actions to words and shows an unknown id as it is", () => {
    data.conns = [
      {
        ...live("Stripe", "stripe", "sandbox"),
        grants: [
          { install: "Order & Payment Reconciliation", capability: "orders.read", access: "read" },
          { install: "Order & Payment Reconciliation", capability: "payment.refund", access: "write" },
          { install: "Order & Payment Reconciliation", capability: "widgets.frobnicate", access: "write" },
        ],
      },
    ];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Read orders")).toBeInTheDocument();
    expect(within(stripe).getByText("Refund payment")).toBeInTheDocument();
    expect(within(stripe).getByText("widgets.frobnicate")).toBeInTheDocument();
  });

  it("maps the capabilities first-party connectors declare to words", () => {
    data.conns = [
      {
        ...live("Stripe", "stripe", "sandbox"),
        grants: [
          { install: "Order & Payment Reconciliation", capability: "payments.read", access: "read" },
          { install: "Order & Payment Reconciliation", capability: "mail.send", access: "write" },
        ],
      },
    ];
    renderWithIntl(<ConnectionList />);
    const stripe = card("Stripe");
    expect(within(stripe).getByText("Read payments")).toBeInTheDocument();
    expect(within(stripe).getByText("Send email")).toBeInTheDocument();
    expect(within(stripe).queryByText("payments.read")).not.toBeInTheDocument();
  });

  it("links an empty list to the marketplace", () => {
    data.conns = [];
    renderWithIntl(<ConnectionList />);
    expect(
      screen.getByText("No apps yet. Add a pack and the apps it needs appear here, ready to connect."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse the marketplace" })).toHaveAttribute("href", "/app/marketplace");
  });

  it("shows both choices in Japanese", () => {
    renderWithIntl(<ConnectionList />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "Shopifyを接続" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Shopifyでシミュレーションデータを使う" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stripeを実際のアカウントに切り替える" })).toBeInTheDocument();
  });
});

describe("ConnectionList on return from an app's sign-in page", () => {
  const connected = () => ({ ...live("Stripe", "stripe", "connected", "composio"), account: "acct_1" });
  const settle = (row: () => unknown) =>
    sync.mockImplementation((_vars: unknown, opts: Answer & { onSettled: () => void }) => {
      opts.onSuccess(row());
      opts.onSettled();
    });

  beforeEach(() => {
    data.conns = [live("Stripe", "stripe", "pending", "composio")];
    nav.search = "connected=stripe&status=success";
  });

  it("finishes the connection once, says so and drops the query", async () => {
    settle(connected);
    const { rerender } = renderWithIntl(<ConnectionList />);
    rerender(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false }));
    expect(sync).toHaveBeenCalledTimes(1);
    expect(sync).toHaveBeenCalledWith({ path: { app_name: "stripe" } }, expect.anything());
    expect(toast).toHaveBeenCalledWith(
      "Stripe connected",
      "Packs you added now use your real Stripe account, within the access you grant them.",
    );
    expect(leaveFor).not.toHaveBeenCalled();
  });

  it("asks once even under strict mode, and once the list is refetched", async () => {
    settle(() => {
      data.conns = [connected()];
      return connected();
    });
    const { rerender } = renderWithIntl(
      <StrictMode>
        <ConnectionList />
      </StrictMode>,
    );
    rerender(
      <StrictMode>
        <ConnectionList />
      </StrictMode>,
    );
    await waitFor(() => expect(nav.replace).toHaveBeenCalled());
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("moves focus to the connected app's Disconnect control", async () => {
    settle(() => {
      data.conns = [connected()];
      return connected();
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Stripe")).getByRole("button", { name: "Disconnect Stripe" })).toHaveFocus(),
    );
  });

  it("says when signing in is not finished yet, keeps the row and focuses Finish connecting", async () => {
    settle(() => live("Stripe", "stripe", "pending", "composio"));
    renderWithIntl(<ConnectionList />);
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Signing in to Stripe is not finished",
        "Finish signing in on the Stripe page, then come back here.",
        "blocked",
      ),
    );
    expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false });
    expect(connect).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Finish connecting Stripe" })).toHaveFocus());
  });

  it("moves focus to Connect when the sign-in did not finish", async () => {
    settle(() => {
      data.conns = [live("Stripe", "stripe", "not_connected")];
      return live("Stripe", "stripe", "not_connected");
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    rerender(<ConnectionList />);
    await waitFor(() => expect(within(card("Stripe")).getByRole("button", { name: "Connect Stripe" })).toHaveFocus());
  });

  it("moves focus to Disconnect when the app was switched to simulated data meanwhile", async () => {
    settle(() => {
      data.conns = [live("Stripe", "stripe", "sandbox")];
      return live("Stripe", "stripe", "sandbox");
    });
    const { rerender } = renderWithIntl(<ConnectionList />);
    rerender(<ConnectionList />);
    await waitFor(() =>
      expect(within(card("Stripe")).getByRole("button", { name: "Disconnect Stripe" })).toHaveFocus(),
    );
    expect(toast).not.toHaveBeenCalled();
  });

  it("leaves focus alone when asking the API fails", async () => {
    sync.mockImplementation((_vars: unknown, opts: { onError: (e: unknown) => void; onSettled: () => void }) => {
      opts.onError(new Error("offline"));
      opts.onSettled();
    });
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalled());
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    expect(document.activeElement).toBe(document.body);
  });

  it("asks about a real account that needs signing in again", async () => {
    data.conns = [live("Stripe", "stripe", "needs_reauth", "composio")];
    settle(connected);
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalled());
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("only drops the query when the listed app is not a real account (a stale return)", async () => {
    data.conns = [live("Stripe", "stripe", "sandbox")];
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false }));
    expect(sync).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it("does nothing in the demo workspace", () => {
    data.demo = true;
    renderWithIntl(<ConnectionList />);
    expect(sync).not.toHaveBeenCalled();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("says when the sign-in failed", async () => {
    settle(() => live("Stripe", "stripe", "not_connected"));
    renderWithIntl(<ConnectionList />);
    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        "Could not connect Stripe",
        "The sign-in did not finish. Try again, or use simulated data.",
        "blocked",
      ),
    );
  });

  it("claims nothing when the app was switched to simulated data meanwhile", async () => {
    settle(() => live("Stripe", "stripe", "sandbox"));
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false }));
    expect(sync).toHaveBeenCalledTimes(1);
    expect(toast).not.toHaveBeenCalled();
  });

  it("names the app, not its key, when asking the API fails", async () => {
    sync.mockImplementation((_vars: unknown, opts: { onError: (e: unknown) => void; onSettled: () => void }) => {
      opts.onError(new Error("offline"));
      opts.onSettled();
    });
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Could not connect Stripe", expect.any(String), "blocked"));
    expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false });
  });

  it("ignores a key the workspace does not list, and still drops the query", async () => {
    nav.search = "connected=gmail";
    renderWithIntl(<ConnectionList />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/app/connections", { scroll: false }));
    expect(sync).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it("does nothing without the query", () => {
    nav.search = "";
    renderWithIntl(<ConnectionList />);
    expect(sync).not.toHaveBeenCalled();
    expect(nav.replace).not.toHaveBeenCalled();
  });
});

describe("ConnectionList in the demo workspace", () => {
  it("keeps the explanatory connect dialog for apps the demo cannot connect", async () => {
    data.demo = true;
    data.conns = [
      {
        app: "Slack",
        status: "not_connected",
        provider: "Composio",
        account: "",
        oauthScopes: [],
        grants: [],
        revoked: [],
      },
    ];
    renderWithIntl(<ConnectionList />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Slack" }));
    expect(connect).not.toHaveBeenCalled();
    expect(await screen.findByText(/This demo workspace cannot connect real accounts/)).toBeInTheDocument();
  });
});
