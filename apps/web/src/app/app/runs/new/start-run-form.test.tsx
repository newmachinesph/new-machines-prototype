import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ApiError } from "@/lib/api/errors";
import { StartRunFields, StartRunForm, makeStartRunSchema, refusalFor } from "./start-run-form";

const detail = vi.hoisted(() => ({ query: { isPending: true, isError: false } as Record<string, unknown> }));
vi.mock("@/lib/queries/catalog", () => ({ usePack: () => detail.query }));
const start = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("@/lib/queries/runs", () => ({ useStartRun: () => ({ mutate: start.mutate, isPending: false }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));

const packs = [
  {
    slug: "order-payment-reconciliation",
    name: "Order & Payment Reconciliation",
    inputs: ["Google Sheets: Orders Oct 11"],
  },
];

describe("StartRunFields", () => {
  it("submits the chosen pack, input and budget", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(
      <StartRunFields packs={packs} defaultPack="order-payment-reconciliation" onSubmit={onSubmit} pending={false} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith({
      packSlug: "order-payment-reconciliation",
      input: "Google Sheets: Orders Oct 11",
      budgetMinor: 5000,
      note: "",
    });
  });

  it("explains a missing input instead of submitting", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(
      <StartRunFields
        packs={[{ ...packs[0], inputs: [] }]}
        defaultPack="order-payment-reconciliation"
        onSubmit={onSubmit}
        pending={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Connect an app with this data first.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the missing-input message in Japanese", async () => {
    renderWithIntl(
      <StartRunFields
        packs={[{ ...packs[0], inputs: [] }]}
        defaultPack="order-payment-reconciliation"
        onSubmit={vi.fn()}
        pending={false}
      />,
      { locale: "ja" },
    );
    await userEvent.click(screen.getByRole("button", { name: "実行を開始" }));
    expect(await screen.findByText("先に、このデータのアプリを接続してください。")).toBeInTheDocument();
  });
});

describe("makeStartRunSchema", () => {
  const messages = { choosePack: "pack!", needInput: "input!", noteTooLong: "note!" } as const;
  const schema = makeStartRunSchema((key) => messages[key]);

  it("reports each problem with the translated message", () => {
    const result = schema.safeParse({ packSlug: "", input: "", budgetMinor: 5000, note: "x".repeat(501) });
    expect(result.success).toBe(false);
    expect(result.error?.issues.map((i) => i.message)).toEqual(["pack!", "input!", "note!"]);
  });

  it("accepts a complete form", () => {
    expect(schema.safeParse({ packSlug: "a", input: "b", budgetMinor: 2000, note: "" }).success).toBe(true);
  });
});

const RECON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["since", "until"],
  properties: {
    since: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$", description: "First day to reconcile." },
    until: { type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" },
  },
};

const NESTED_SCHEMA = {
  type: "object",
  required: ["range"],
  properties: {
    dryRun: { type: "boolean", title: "Dry run" },
    region: { type: "string", enum: ["us", "jp"], default: "us" },
    limit: { type: "integer" },
    range: {
      type: "object",
      title: "Date range",
      required: ["from"],
      properties: { from: { type: "string", format: "date" }, to: { type: "string", format: "date" } },
    },
  },
};

const fields = (extra: Partial<Parameters<typeof StartRunFields>[0]> = {}) => (
  <StartRunFields
    packs={[{ ...packs[0], inputs: [] }]}
    defaultPack="order-payment-reconciliation"
    onSubmit={vi.fn()}
    pending={false}
    schema={RECON_SCHEMA}
    {...extra}
  />
);

describe("StartRunFields from an input schema", () => {
  it("builds date fields from the schema and submits the input as an object", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(fields({ onSubmit }));
    expect(screen.getByText("First day to reconcile.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Since"), { target: { value: "2026-10-06" } });
    fireEvent.change(screen.getByLabelText("Until"), { target: { value: "2026-10-12" } });
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith({
      packSlug: "order-payment-reconciliation",
      input: { since: "2026-10-06", until: "2026-10-12" },
      budgetMinor: 5000,
      note: "",
    });
  });

  it("names each missing required field instead of submitting", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(fields({ onSubmit }));
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Enter Since.")).toBeInTheDocument();
    expect(screen.getByText("Enter Until.")).toBeInTheDocument();
    expect(screen.getByLabelText("Since")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("names a missing field in Japanese", async () => {
    renderWithIntl(fields(), { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "実行を開始" }));
    expect(await screen.findByText("Sinceを入力してください。")).toBeInTheDocument();
  });

  it("groups one level of nesting and supports booleans, enums and integers", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(fields({ onSubmit, schema: NESTED_SCHEMA }));
    expect(screen.getByRole("group", { name: "Date range" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByLabelText(/Limit/), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ input: { dryRun: true, region: "us", limit: 20, range: { from: "2026-10-01" } } }),
    );
  });

  it("puts the API's field errors on their fields and lists the rest", async () => {
    renderWithIntl(
      fields({
        issues: [
          { kind: "input", key: "recon", path: "since", message: "'2026-13-01' is not a valid date" },
          { kind: "input", key: "recon", path: "", message: "The input is too large." },
        ],
      }),
    );
    expect(await screen.findByText("'2026-13-01' is not a valid date")).toBeInTheDocument();
    expect(screen.getByLabelText("Since")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("The input is too large.")).toBeInTheDocument();
  });

  it("explains a known refusal, links to the fix and holds the start button", () => {
    renderWithIntl(
      fields({
        refusal: {
          text: "Connect Stripe before starting a run.",
          href: "/app/connections",
          action: "Go to connections",
        },
        refusalBlocks: true,
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Connect Stripe before starting a run.");
    expect(screen.getByRole("link", { name: "Go to connections" })).toHaveAttribute("href", "/app/connections");
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("keeps the start button for a refusal the person can retry after changing the form", () => {
    renderWithIntl(fields({ refusal: { text: "Lower the budget." } }));
    expect(screen.getByRole("button", { name: "Start run" })).toBeEnabled();
  });
});

describe("refusalFor", () => {
  const t = (key: string) => key;
  const refusal = (status: number, code: string) =>
    refusalFor(new ApiError(status, code, `detail of ${code}`), "recon", t as never);

  it("links each start refusal to the page that fixes it", () => {
    expect(refusal(409, "PACK_NOT_HIRED")).toEqual({
      text: "detail of PACK_NOT_HIRED",
      href: "/app/marketplace/recon",
      action: "hireThis",
    });
    expect(refusal(409, "APPS_NOT_CONNECTED")?.href).toBe("/app/connections");
    expect(refusal(409, "SPEND_CAP")?.href).toBe("/app/usage");
    expect(refusal(409, "RUN_BUDGET_OVER_CAP")?.href).toBe("/app/marketplace/recon/install");
  });

  it("shows an unknown refusal's own words, and leaves server failures to the toast", () => {
    expect(refusal(409, "SOMETHING_NEW")).toEqual({ text: "detail of SOMETHING_NEW" });
    expect(refusal(503, "RUNTIME_UNAVAILABLE")).toBeNull();
  });
});

describe("StartRunFields and the pack's per-run cap", () => {
  const capped = (amountMinor: number) => [{ ...packs[0], perRunCap: { amountMinor, currency: "USD" as const } }];

  it("starts at the cap when it is below the usual budget, and says what the cap is", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(<StartRunFields packs={capped(2000)} onSubmit={onSubmit} pending={false} />);
    expect(screen.getByText(/This pack's spending cap per run is \$20\.00\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Change the per-run cap" })).toHaveAttribute(
      "href",
      "/app/marketplace/order-payment-reconciliation/install",
    );
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ budgetMinor: 2000 }));
  });

  it("offers a cap that is not one of the usual budgets as a choice", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(<StartRunFields packs={capped(500)} onSubmit={onSubmit} pending={false} />);
    expect(screen.getByRole("radio", { name: "$5.00" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ budgetMinor: 500 }));
  });

  it("keeps the usual budget when the cap is higher, or when there is none", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(<StartRunFields packs={capped(10000)} onSubmit={onSubmit} pending={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ budgetMinor: 5000 }));
  });
});

const EDGE_SCHEMA = {
  type: "object",
  properties: {
    limit: { type: "integer" },
    region: { type: "string", enum: ["us", "jp"], title: "Region" },
    notify: { type: "boolean", title: "Notify", description: "Email me when it finishes." },
    window: {
      type: "object",
      title: "Window",
      required: ["start"],
      properties: { start: { type: "string", format: "date" }, end: { type: "string", format: "date" } },
    },
  },
};

describe("StartRunFields edge cases", () => {
  it("flags a number that isn't one instead of dropping it", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(fields({ onSubmit, schema: EDGE_SCHEMA }));
    await userEvent.type(screen.getByLabelText(/Limit/), "12abc");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Enter a whole number.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Limit/)).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("lets an optional choice without a default stay empty", () => {
    renderWithIntl(fields({ schema: EDGE_SCHEMA }));
    expect(screen.getByRole("combobox", { name: "Region" })).toHaveTextContent("None");
  });

  it("describes a checkbox by its help text", () => {
    renderWithIntl(fields({ schema: EDGE_SCHEMA }));
    expect(screen.getByRole("checkbox", { name: /Notify/ })).toHaveAccessibleDescription("Email me when it finishes.");
  });

  it("leaves an untouched optional object out, and asks for its required field once it is started", async () => {
    const onSubmit = vi.fn();
    renderWithIntl(fields({ onSubmit, schema: EDGE_SCHEMA }));
    const legend = screen.getByRole("group", { name: /Window/ });
    expect(legend).toHaveAccessibleName(/^Window\s*\(optional\)$/);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ input: { notify: false } }));
    fireEvent.change(within(legend).getByLabelText(/^End/), { target: { value: "2026-10-10" } });
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Enter Start.")).toBeInTheDocument();
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("focuses the first field the API's errors land on", async () => {
    renderWithIntl(
      fields({ issues: [{ kind: "input", key: "recon", path: "until", message: "Until is before Since." }] }),
    );
    await waitFor(() => expect(screen.getByLabelText("Until")).toHaveFocus());
  });

  it("shows a schema-less pack's input errors once, on its input", async () => {
    renderWithIntl(
      <StartRunFields
        packs={packs}
        onSubmit={vi.fn()}
        pending={false}
        issues={[{ kind: "input", key: "free", path: "", message: "That sheet has no orders." }]}
      />,
    );
    expect(await screen.findByText("That sheet has no orders.")).toBeInTheDocument();
    expect(screen.getAllByText("That sheet has no orders.")).toHaveLength(1);
  });
});

class Boundary extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {};
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    return this.state.error ? <p>page error: {this.state.error.message}</p> : this.props.children;
  }
}

describe("StartRunForm", () => {
  it("reports a pack detail that failed to load instead of a form that can't start", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    detail.query = { isPending: false, isError: true, data: undefined, error: new Error("pack unavailable") };
    renderWithIntl(
      <Boundary>
        <StartRunForm packs={packs} />
      </Boundary>,
    );
    expect(screen.getByText("page error: pack unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start run" })).not.toBeInTheDocument();
    vi.mocked(console.error).mockRestore();
  });

  it("builds the overdue pack's form from its input schema: one As of date, sent as as_of", async () => {
    // definitions/packs/overdue-invoice-follow-up/schemas/input.json
    const overdueSchema = {
      $schema: "https://json-schema.org/draft/2020-12/schema",
      title: "Overdue invoice follow-up request",
      type: "object",
      additionalProperties: false,
      required: ["as_of"],
      properties: {
        as_of: {
          type: "string",
          pattern: "^\\d{4}-\\d{2}-\\d{2}$",
          description: "The day to measure lateness from (YYYY-MM-DD). Invoices due before this day are overdue.",
        },
      },
    };
    detail.query = { isPending: false, isError: false, data: { inputSchema: overdueSchema } };
    start.mutate.mockClear();
    const overdue = [{ slug: "overdue-invoice-follow-up", name: "Overdue Invoice Follow-up", inputs: [] }];
    const { container } = renderWithIntl(<StartRunForm packs={overdue} />);
    const asOf = screen.getByLabelText("As of");
    expect(asOf).toHaveAttribute("type", "date");
    expect(container.querySelectorAll("input[type=date]")).toHaveLength(1);
    expect(container.querySelector("#run-input")).toBeNull(); // no free-text input
    fireEvent.change(asOf, { target: { value: "2026-10-13" } });
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(start.mutate).toHaveBeenCalledTimes(1));
    expect(start.mutate.mock.calls[0][0].body).toEqual({
      packSlug: "overdue-invoice-follow-up",
      input: { as_of: "2026-10-13" },
      budgetMinor: 5000,
      note: undefined,
    });
  });
});
