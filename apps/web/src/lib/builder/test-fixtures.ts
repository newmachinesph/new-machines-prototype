/**
 * Test data: the seed overdue invoice pack (definitions/packs/overdue-invoice-follow-up/workflow.yaml) as the
 * API's import returns it, with connector "next" read as "ok" and the decision's rules inline, and a palette
 * with the tools and agents it uses. `stripe.refund_charge` is made up: it moves money, so a pack may not use it.
 */
import type { PackDraft, Palette } from "@/lib/api/gen/types.gen";

const DRAFTS_SCHEMA = {
  title: "Email drafts",
  type: "object",
  required: ["drafts"],
  properties: {
    drafts: {
      type: "array",
      title: "Drafts",
      items: {
        type: "object",
        properties: {
          to: { type: "string", title: "To" },
          subject: { type: "string", title: "Subject" },
          body: { type: "string", title: "Body" },
          ref: { type: "string" },
        },
      },
    },
  },
};

const PLAN_SCHEMA = {
  title: "Reminder plan",
  type: "object",
  properties: {
    messages: { type: "array", title: "Messages", items: { type: "object", properties: { ref: { type: "string" } } } },
    review_items: { type: "array", title: "Review items" },
  },
};

export const OVERDUE: PackDraft = {
  name: "Overdue invoice follow-up",
  outcome: "Every overdue invoice gets a reminder draft.",
  description: "Finds overdue invoices, plans reminders, and saves drafts after a person approves.",
  humanReview: "A person checks the reminder plan and approves the drafts.",
  function: "finance-ops",
  industries: ["retail-commerce"],
  inputFields: [{ name: "as_of", label: "As of", type: "date", required: true }],
  budgetMinor: 1500,
  humanBudgetMinor: 0,
  entryStep: "start",
  steps: [
    { id: "start", type: "trigger", config: {}, routes: { next: "recall" } },
    {
      id: "recall",
      type: "memory",
      config: { op: "recall", space: "customer-accounts", query: "collections reminders tone overdue" },
      routes: { next: "invoices" },
    },
    {
      id: "invoices",
      type: "connector",
      config: { tool: "stripe.list_invoices", args: { status: "open", limit: 100 } },
      routes: { ok: "plan", denied: "failed", error: "failed" },
    },
    {
      id: "plan",
      type: "agent",
      config: {
        agent: "collections-agent",
        task: "Find the invoices that are overdue and plan one reminder each.",
        inputs: { invoices: "=nodes.invoices.output", as_of: "=input.as_of", rules: "=memory" },
        output_schema: "overdue-invoice-follow-up/plan",
      },
      routes: { next: "check" },
    },
    {
      id: "check",
      type: "decision",
      config: {},
      routes: { nothing: "nothing", human_review: "review" },
      rules: {
        question: "Are there overdue invoices to follow up?",
        rules: [
          {
            when: "size(nodes.plan.output.messages) == 0",
            route: "nothing",
            verdict: "APPROVED",
            explanation: "No open invoice is past its due date, so there is nobody to remind.",
          },
        ],
        default: {
          route: "human_review",
          verdict: "HUMAN_REVIEW",
          explanation: "Some invoices are overdue, so a person checks the reminder plan before any draft is written.",
        },
      },
    },
    {
      id: "review",
      type: "human_workforce",
      config: {
        title: "Check the overdue invoice reminders",
        instructions: "Check each invoice and its reminder stage.",
        show: "=nodes.plan.output.review_items",
        timeout_s: 86400,
      },
      routes: { resolved: "draft", rejected: "failed", timeout: "failed" },
    },
    {
      id: "draft",
      type: "agent",
      config: {
        agent: "writer-agent",
        task: "Write one short, polite email draft per item.",
        inputs: { items: "=nodes.plan.output.messages", review: "=nodes.review.output", tone: "firm but friendly" },
        output_schema: "shared/drafts",
      },
      routes: { next: "approve" },
    },
    {
      id: "approve",
      type: "approval",
      config: {
        title: "Save the reminder emails as drafts",
        summary: "='Create ' + string(size(nodes.draft.output.drafts)) + ' email drafts in Gmail'",
        timeout_s: 86400,
      },
      routes: { granted: "send", denied: "failed", timeout: "failed" },
    },
    {
      id: "send",
      type: "connector",
      config: {
        tool: "gmail.create_draft",
        for_each: "=nodes.draft.output.drafts",
        args: { recipient_email: "=item.to", subject: "=item.subject", body: "=item.body" },
      },
      routes: { ok: "verify", denied: "failed", error: "failed" },
    },
    {
      id: "verify",
      type: "verification",
      config: {
        schema: "shared/drafts",
        value: "=nodes.draft.output",
        checks: ["=size(nodes.draft.output.drafts) >= 1"],
      },
      routes: { pass: "done", fail: "failed" },
    },
    { id: "nothing", type: "end", config: { status: "COMPLETED", deliverable: "=nodes.plan.output" }, routes: {} },
    { id: "done", type: "end", config: { status: "COMPLETED", deliverable: "=nodes.draft.output" }, routes: {} },
    { id: "failed", type: "end", config: { status: "FAILED" }, routes: {} },
  ],
};

const tool = (
  app: string,
  appName: string,
  id: string,
  actionClass: string,
  capability: string,
  properties: Record<string, unknown>,
  required: string[] = [],
) => ({
  ref: `${app}.${id}`,
  app: appName,
  name: id.replace("_", " ").replace(/^./, (c) => c.toUpperCase()),
  description: `${appName} ${id}`,
  actionClass,
  capability,
  // Shaped like the connector definitions: closed objects with their required args named.
  inputSchema: { type: "object", additionalProperties: false, required, properties },
});

export const PALETTE: Palette = {
  agents: [
    {
      key: "collections-agent",
      name: "Collections Agent",
      summary: "Plans reminders for overdue invoices.",
      modelProfile: "reasoning",
      outputSchemaRef: "overdue-invoice-follow-up/plan",
      outputSchema: PLAN_SCHEMA,
    },
    {
      key: "org-a1--invoice-helper",
      name: "Invoice helper",
      summary: "Finds open invoices.",
      builtByTeam: true,
      modelProfile: "fast",
      outputSchemaRef: "shared/agent-result",
    },
    {
      key: "writer-agent",
      name: "Writer Agent",
      summary: "Writes short emails.",
      modelProfile: "fast",
      outputSchemaRef: "shared/drafts",
      outputSchema: DRAFTS_SCHEMA,
    },
  ],
  tools: [
    tool(
      "gmail",
      "Gmail",
      "create_draft",
      "write",
      "mail.write",
      {
        recipient_email: { type: "string", description: "The address the draft is to." },
        subject: { type: "string", description: "The subject line." },
        body: { type: "string", description: "The plain-text body." },
      },
      ["recipient_email", "subject", "body"],
    ),
    tool("stripe", "Stripe", "list_invoices", "read", "invoices.read", {
      status: { type: "string", description: "Which invoices." },
      limit: { type: "integer", description: "Most invoices to return." },
    }),
    tool("stripe", "Stripe", "refund_charge", "money", "payments.refund", {}),
  ],
  spaces: [{ key: "customer-accounts", name: "Customer accounts" }],
  schemas: [{ key: "shared/drafts", title: "Email drafts", body: DRAFTS_SCHEMA }],
};
