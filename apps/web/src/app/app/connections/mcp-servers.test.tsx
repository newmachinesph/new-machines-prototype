import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { mcpServer } from "@/test/mcp";
import { McpServers } from "./mcp-servers";

const mocks = vi.hoisted(() => ({
  live: true,
  role: "owner",
  servers: [] as unknown[],
  refresh: vi.fn(),
  replace: vi.fn(),
  replaceReset: vi.fn(),
  remove: vi.fn(),
  toast: vi.fn(),
}));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => mocks.toast,
}));
vi.mock("@/lib/queries/me", () => ({
  useIsLive: () => mocks.live,
  useMe: () => ({ data: { role: mocks.role } }),
  useOrgId: () => "org_a1",
}));
vi.mock("@/lib/queries/mcp", () => ({
  useMcpServers: () => ({ isPending: false, isError: false, data: mocks.servers }),
  useRefreshMcpServer: () => ({ mutate: mocks.refresh, isPending: false }),
  useReplaceMcpToken: () => ({ mutate: mocks.replace, reset: mocks.replaceReset, isPending: false }),
  useRemoveMcpServer: () => ({ mutate: mocks.remove, isPending: false }),
  useSwitchMcpTool: () => ({ on: { mutate: vi.fn() }, off: { mutate: vi.fn() } }),
}));
vi.mock("./add-mcp-server", () => ({
  AddMcpServer: () => <button type="button">Add your own MCP server</button>,
  INPUT_CLASS: "",
}));

type Handlers = { onSuccess?: (v: unknown) => void; onError?: (e: unknown) => void };
const PATH = { org_id: "org_a1", server_id: "mcp_0123456789ab" };

beforeEach(() => {
  for (const m of [mocks.refresh, mocks.replace, mocks.replaceReset, mocks.remove, mocks.toast]) m.mockReset();
  mocks.live = true;
  mocks.role = "owner";
  mocks.servers = [mcpServer()];
});

describe("McpServers", () => {
  it("shows each server with its status, address, tools in use and token ending", () => {
    renderWithIntl(<McpServers />);
    expect(screen.getByRole("heading", { name: "Your MCP servers" })).toBeInTheDocument();
    const card = screen.getByRole("heading", { name: "Acme CRM" }).closest("li")!;
    expect(within(card).getByText("Connected")).toBeInTheDocument();
    expect(within(card).getByText("https://mcp.acme.test/mcp")).toBeInTheDocument();
    expect(within(card).getByText(/2 tools in use/)).toBeInTheDocument();
    expect(within(card).getByText(/Token ending 1234/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add your own MCP server" })).toBeInTheDocument();
  });

  it("says when a server stopped answering", () => {
    mocks.servers = [mcpServer({ status: "failing", lastError: "unreachable" })];
    renderWithIntl(<McpServers />);
    expect(screen.getByText("Not answering")).toBeInTheDocument();
    expect(screen.getByText("The last call got no answer.")).toBeInTheDocument();
  });

  it("refreshes the tools and says how many packs can use", async () => {
    mocks.refresh.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer({ toolCount: 3 })));
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Refresh tools of Acme CRM" }));
    expect(mocks.refresh.mock.calls[0][0]).toEqual({ path: PATH });
    expect(mocks.toast).toHaveBeenCalledWith("Tools refreshed", "Acme CRM lists 3 tools your packs can use.");
  });

  it("replaces the token", async () => {
    mocks.replace.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer({ tokenLast4: "5678" })));
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Replace token of Acme CRM" }));
    await userEvent.type(screen.getByLabelText("Token"), "fresh-token-5678");
    await userEvent.click(screen.getByRole("button", { name: "Replace token" }));
    expect(mocks.replace.mock.calls[0][0]).toEqual({ path: PATH, body: { token: "fresh-token-5678" } });
    expect(mocks.toast).toHaveBeenCalledWith("Token replaced");
  });

  it("resets the replace request on success", async () => {
    mocks.replace.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Replace token of Acme CRM" }));
    await userEvent.type(screen.getByLabelText("Token"), "fresh-token-5678");
    await userEvent.click(screen.getByRole("button", { name: "Replace token" }));
    expect(mocks.replaceReset).toHaveBeenCalled();
  });

  it("clears a typed token and resets the request when closed without submitting", async () => {
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Replace token of Acme CRM" }));
    await userEvent.type(screen.getByLabelText("Token"), "typed-secret");
    await userEvent.keyboard("{Escape}");
    expect(mocks.replaceReset).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Replace token of Acme CRM" }));
    expect(screen.getByLabelText("Token")).toHaveValue("");
  });

  it("removes a server after confirming", async () => {
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Remove Acme CRM" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove server" }));
    expect(mocks.remove.mock.calls[0][0]).toEqual({ path: PATH });
  });

  it("shows the tools in their groups", async () => {
    renderWithIntl(<McpServers />);
    await userEvent.click(screen.getByRole("button", { name: "Tools of Acme CRM" }));
    expect(screen.getByRole("region", { name: "Blocked" })).toBeInTheDocument();
  });

  it("lets a member look but not change anything", async () => {
    mocks.role = "member";
    renderWithIntl(<McpServers />);
    expect(screen.getByText("Ask an owner or admin to add an MCP server.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add your own MCP server" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh tools of Acme CRM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Acme CRM" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tools of Acme CRM" }));
    expect(screen.getByRole("checkbox", { name: "get_customer" })).toHaveAttribute("aria-disabled", "true");
  });

  it("says when there are none", () => {
    mocks.servers = [];
    renderWithIntl(<McpServers />);
    expect(screen.getByText("No MCP servers yet.")).toBeInTheDocument();
  });

  it("is not part of the demo", () => {
    mocks.live = false;
    renderWithIntl(<McpServers />);
    expect(screen.queryByRole("heading", { name: "Your MCP servers" })).not.toBeInTheDocument();
  });
});
