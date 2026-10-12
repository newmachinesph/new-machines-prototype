import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CapUsage, capLevel } from "./cap-usage";

const usd = (n: number) => ({ amountMinor: n, currency: "USD" as const });

describe("capLevel", () => {
  it("switches at 80% and 90%", () => {
    expect(capLevel(0.79)).toBe("ok");
    expect(capLevel(0.8)).toBe("warn");
    expect(capLevel(0.899)).toBe("warn");
    expect(capLevel(0.9)).toBe("blocked");
    expect(capLevel(1.4)).toBe("blocked");
  });
});

describe("CapUsage", () => {
  it("shows the percentage and the amounts", () => {
    render(<CapUsage spent={usd(85000)} cap={usd(100000)} showAmounts />);
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "85");
  });
  it("clamps the bar at the cap but reports the real overspend", () => {
    render(<CapUsage spent={usd(150000)} cap={usd(100000)} />);
    expect(screen.getByText("150%")).toBeInTheDocument();
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "100");
    expect(meter).toHaveAttribute("aria-valuetext", "150% of the monthly cap");
  });
  it("treats a zero cap as full", () => {
    render(<CapUsage spent={usd(0)} cap={usd(0)} />);
    expect(screen.getByText("100%")).toBeInTheDocument();
  });
});
