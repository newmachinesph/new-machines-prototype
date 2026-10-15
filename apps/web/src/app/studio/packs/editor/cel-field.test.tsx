import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { CelField } from "./cel-field";

const OPTIONS = [
  { group: "input" as const, expr: "input.as_of", label: "As of" },
  { group: "steps" as const, expr: "nodes.plan.output.review_items", label: "plan · Review items" },
];

const FIXED = [
  { group: "memory" as const, expr: "memory", label: "memory", fixed: "memory" as const },
  { group: "steps" as const, expr: "nodes.send.output.results", label: "send · results", fixed: "results" as const },
  { group: "item" as const, expr: "item", label: "item", fixed: "item" as const },
];

describe("CelField", () => {
  it("inserts a field chosen from the picker as an expression", async () => {
    const onChange = vi.fn();
    renderWithIntl(
      <CelField id="show" label="What the reviewer sees" value="" onChange={onChange} options={OPTIONS} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Fields to insert into What the reviewer sees" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /plan · Review items/ }));
    expect(onChange).toHaveBeenCalledWith("=nodes.plan.output.review_items", true);
  });

  it("names each group of fields for assistive technology", async () => {
    renderWithIntl(<CelField id="show" label="Show" value="" onChange={vi.fn()} options={OPTIONS} />);
    await userEvent.click(screen.getByRole("button", { name: "Fields to insert into Show" }));
    const steps = await screen.findByRole("group", { name: "Earlier steps" });
    expect(within(steps).getByRole("menuitem", { name: /plan · Review items/ })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Run input" })).toBeInTheDocument();
  });

  it("translates the fixed words memory, item and results", async () => {
    renderWithIntl(<CelField id="show" label="Show" value="" onChange={vi.fn()} options={FIXED} />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("menuitem", { name: /呼び出した内容/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /^send · 結果/ })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /現在の項目/ })).toBeInTheDocument();
    expect(screen.queryByText("memory memory")).toBeNull();
  });

  it("passes typing through without recording each key, and says whether the value is an expression", async () => {
    const onChange = vi.fn();
    const { rerender } = renderWithIntl(
      <CelField id="tone" label="Tone" value="" onChange={onChange} options={OPTIONS} />,
    );
    await userEvent.type(screen.getByLabelText("Tone"), "f");
    expect(onChange).toHaveBeenCalledWith("f", false);
    expect(screen.getByText(/Plain text/)).toBeInTheDocument();
    rerender(<CelField id="tone" label="Tone" value="=input.as_of" onChange={onChange} options={OPTIONS} />);
    expect(screen.getByText(/An expression/)).toBeInTheDocument();
  });

  it("shows a long value in monospace once it is an expression, like the short one", () => {
    const { rerender } = renderWithIntl(
      <CelField id="task" label="Task" value="Write one draft." onChange={vi.fn()} options={OPTIONS} multiline />,
    );
    expect(screen.getByLabelText("Task")).not.toHaveClass("font-mono");
    rerender(
      <CelField id="task" label="Task" value="=nodes.plan.output" onChange={vi.fn()} options={OPTIONS} multiline />,
    );
    expect(screen.getByLabelText("Task")).toHaveClass("font-mono");
  });
});
