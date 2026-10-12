import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UsageChart } from "./usage-chart";

const pts = [
  { day: "2026-10-10", amountMinor: 1000 },
  { day: "2026-10-11", amountMinor: 0 },
  { day: "2026-10-12", amountMinor: 4000 },
];

describe("UsageChart", () => {
  it("labels the chart with total and peak and lists every day", () => {
    render(<UsageChart points={pts} />);
    expect(screen.getByRole("img", { name: /3 days, \$50\.00 in total, peak \$40\.00/ })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });
  it("says so when there is no usage", () => {
    render(<UsageChart points={[]} />);
    expect(screen.getByText(/No usage/)).toBeInTheDocument();
  });
});
