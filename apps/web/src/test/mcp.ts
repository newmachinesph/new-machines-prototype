import type { McpServer } from "@/lib/api/gen/types.gen";

/** An added server as the API answers: one tool runs freely, two ask first (one switched off), one is blocked. */
export const mcpServer = (over: Partial<McpServer> = {}): McpServer => ({
  id: "mcp_0123456789ab",
  name: "Acme CRM",
  url: "https://mcp.acme.test/mcp",
  headerName: "Authorization",
  tokenLast4: "1234",
  status: "active",
  connectorKey: "org-a1--acme-crm",
  toolCount: 2,
  tools: [
    {
      id: "get_customer",
      name: "get_customer",
      description: "Look up a customer.",
      toolClass: "read",
      why: "marked_read_only",
      on: true,
    },
    {
      id: "update_customer_note",
      name: "update_customer_note",
      description: "Change a note.",
      toolClass: "write",
      why: "changes_data",
      on: true,
    },
    {
      id: "send_survey",
      name: "send_survey",
      description: "Send a survey.",
      toolClass: "write",
      why: "changes_data",
      on: false,
    },
    {
      id: "delete_customer",
      name: "delete_customer",
      description: "Delete a customer.",
      toolClass: "blocked",
      why: "marked_destructive",
      on: false,
    },
  ],
  createdAt: "2026-10-16T09:00:00Z",
  ...over,
});
