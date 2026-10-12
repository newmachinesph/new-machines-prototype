import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttentionQueue } from "./attention-queue";

const base = { kind: "incident", detail: "d", at: "2026-10-12T16:00:00Z" } as const;

describe("AttentionQueue", () => {
  it("lists items by severity, each linking to its href", () => {
    render(
      <AttentionQueue
        items={[
          { ...base, title: "Info item", severity: "info", href: "/health" },
          { ...base, title: "Critical item", severity: "critical", href: "/connectors?c=x" },
        ]}
      />,
    );
    const links = screen.getAllByRole("link");
    expect(links[0]).toHaveTextContent("Critical: Critical item");
    expect(links[0]).toHaveAttribute("href", "/connectors?c=x");
    expect(links[1]).toHaveAttribute("href", "/health");
  });

  it("gives an empty state", () => {
    render(<AttentionQueue items={[]} />);
    expect(screen.getByText(/Nothing needs attention/)).toBeInTheDocument();
  });
});
