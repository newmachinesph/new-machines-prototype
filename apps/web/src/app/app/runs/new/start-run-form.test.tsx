import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { StartRunFields, makeStartRunSchema } from "./start-run-form";

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
