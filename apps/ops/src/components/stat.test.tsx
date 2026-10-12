import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Stat } from "./stat";

describe("Stat", () => {
  it("shows label, value and sub, with a Simulated tag when asked", () => {
    render(<Stat label="MRR" value="$18,400.00" sub="Up 4% on September" simulated />);
    expect(screen.getByText("MRR")).toBeInTheDocument();
    expect(screen.getByText("$18,400.00")).toBeInTheDocument();
    expect(screen.getByText("Up 4% on September")).toBeInTheDocument();
    expect(screen.getByText("Simulated")).toBeInTheDocument();
  });

  it("becomes a link when given an href", () => {
    render(<Stat label="Active tenants" value="6" href="/tenants?status=active" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/tenants?status=active");
    expect(screen.queryByText("Simulated")).toBeNull();
  });
});
