import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunsChart } from "./runs-chart";

const points = [
  { hour: 0, completed: 4, failed: 0, waiting: 0 },
  { hour: 1, completed: 3, failed: 1, waiting: 2 },
];

describe("RunsChart", () => {
  it("labels the chart, tags it simulated and gives a table alternative", () => {
    render(<RunsChart points={points} />);
    expect(screen.getByRole("img", { name: /Runs by hour today.*10 in total.*Simulated/ })).toBeInTheDocument();
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Runs by hour/ })).toBeInTheDocument();
  });

  it("draws a rect per non-empty segment", () => {
    const { container } = render(<RunsChart points={points} />);
    expect(container.querySelectorAll("svg rect")).toHaveLength(4);
  });
});
