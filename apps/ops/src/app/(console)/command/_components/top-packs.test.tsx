import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TopPacks } from "./top-packs";

describe("TopPacks", () => {
  it("lists packs in the order given, with their run counts", () => {
    render(
      <TopPacks
        packs={[
          { slug: "invoice-chase", name: "Invoice chase", runs: 42 },
          { slug: "refund-review", name: "Refund review", runs: 1 },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Invoice chase");
    expect(items[0]).toHaveTextContent("42 runs");
    expect(items[1]).toHaveTextContent("1 run");
  });

  it("says so when nothing ran", () => {
    render(<TopPacks packs={[]} />);
    expect(screen.getByText("No runs in the last 30 days.")).toBeInTheDocument();
  });
});
