import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { mcpServer } from "@/test/mcp";
import { AddMcpServer } from "./add-mcp-server";

const mocks = vi.hoisted(() => ({
  add: vi.fn(),
  addReset: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  toast: vi.fn(),
  servers: [] as unknown[],
}));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => mocks.toast,
}));
vi.mock("@/lib/queries/me", () => ({ useOrgId: () => "org_a1" }));
vi.mock("@/lib/queries/mcp", () => ({
  useAddMcpServer: () => ({ mutate: mocks.add, reset: mocks.addReset, isPending: false }),
  useMcpServers: () => ({ isPending: false, isError: false, data: mocks.servers }),
  useSwitchMcpTool: () => ({ on: { mutate: mocks.on }, off: { mutate: mocks.off } }),
}));

type Handlers = { onSuccess?: (v: unknown) => void; onError?: (e: unknown) => void };

async function fillAndConnect() {
  await userEvent.click(screen.getByRole("button", { name: "Add your own MCP server" }));
  await userEvent.type(screen.getByLabelText("Name"), "Acme CRM");
  await userEvent.type(screen.getByLabelText("Server address"), "https://mcp.acme.test/mcp");
  await userEvent.type(screen.getByLabelText("Token"), "secret-token-1234");
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
}

const group = (name: string) => screen.getByRole("region", { name });

beforeEach(() => {
  for (const m of [mocks.add, mocks.addReset, mocks.on, mocks.off, mocks.toast]) m.mockReset();
  mocks.servers = [];
});

describe("AddMcpServer", () => {
  it("sends the name, address, header and token, then shows the tools in their groups", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    expect(mocks.add.mock.calls[0][0]).toEqual({
      path: { org_id: "org_a1" },
      body: {
        name: "Acme CRM",
        url: "https://mcp.acme.test/mcp",
        headerName: "Authorization",
        token: "secret-token-1234",
      },
    });
    expect(screen.getByText("Acme CRM is connected")).toBeInTheDocument();
    expect(within(group("Runs freely")).getByRole("checkbox", { name: "get_customer" })).toBeChecked();
    expect(within(group("Asks first")).getByRole("checkbox", { name: "update_customer_note" })).toBeChecked();
    expect(within(group("Asks first")).getByRole("checkbox", { name: "send_survey" })).not.toBeChecked();
    const blocked = within(group("Blocked")).getByRole("checkbox", { name: "delete_customer" });
    expect(blocked).not.toBeChecked();
    expect(blocked).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("The server marks it destructive.")).toBeInTheDocument();
  });

  it("switches a tool off and another on", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    await userEvent.click(screen.getByRole("checkbox", { name: "update_customer_note" }));
    expect(mocks.off.mock.calls[0][0]).toEqual({
      path: { org_id: "org_a1", server_id: "mcp_0123456789ab", tool_id: "update_customer_note" },
    });
    await userEvent.click(screen.getByRole("checkbox", { name: "send_survey" }));
    expect(mocks.on.mock.calls[0][0]).toEqual({
      path: { org_id: "org_a1", server_id: "mcp_0123456789ab", tool_id: "send_survey" },
    });
  });

  it("drops the submitted token from the mutation as soon as the server answers", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    expect(mocks.addReset).toHaveBeenCalled();
  });

  it("clears a typed token and resets the request when closed without submitting", async () => {
    renderWithIntl(<AddMcpServer />);
    await userEvent.click(screen.getByRole("button", { name: "Add your own MCP server" }));
    await userEvent.type(screen.getByLabelText("Token"), "typed-secret");
    await userEvent.keyboard("{Escape}");
    expect(mocks.addReset).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Add your own MCP server" }));
    expect(screen.getByLabelText("Token")).toHaveValue("");
  });

  it("resets the request when Done closes the dialog", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    mocks.addReset.mockClear();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(mocks.addReset).toHaveBeenCalledTimes(1);
  });

  it("does not switch on a blocked tool", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    await userEvent.click(screen.getByRole("checkbox", { name: "delete_customer" }));
    expect(mocks.on).not.toHaveBeenCalled();
    expect(mocks.off).not.toHaveBeenCalled();
  });

  it("links each reason to its switch", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    const blocked = screen.getByRole("checkbox", { name: "delete_customer" });
    expect(blocked).toHaveAccessibleDescription("The server marks it destructive.");
  });

  it("says why an address is refused, in the product's own words", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) =>
      h.onError?.(new ApiError(422, "MCP_URL_REFUSED", "detail as sent")),
    );
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    expect(
      screen.getByText("This address cannot be used. Use an https address on the public internet."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Token")).toHaveValue("secret-token-1234");
  });

  it("closes on Done and opens empty the next time", async () => {
    mocks.add.mockImplementation((_v: unknown, h: Handlers) => h.onSuccess?.(mcpServer()));
    renderWithIntl(<AddMcpServer />);
    await fillAndConnect();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByText("Acme CRM is connected")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add your own MCP server" }));
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Header")).toHaveValue("Authorization");
  });
});
