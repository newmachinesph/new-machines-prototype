import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { ClockProvider, useNow } from "./clock";
import { NOW } from "./format";
import { useFormat } from "./use-format";

function Probe({ since }: { since: string }) {
  const now = useNow();
  const { ago } = useFormat();
  return (
    <p>
      <span data-testid="now">{now}</span> <span data-testid="ago">{ago(since)}</span>
    </p>
  );
}

afterEach(() => vi.useRealTimers());

describe("the workspace clock", () => {
  it("keeps the demo's pinned now", () => {
    renderWithIntl(
      <ClockProvider live={false}>
        <Probe since="2026-10-12T16:10:00Z" />
      </ClockProvider>,
    );
    expect(screen.getByTestId("now")).toHaveTextContent(NOW);
    expect(screen.getByTestId("ago")).toHaveTextContent("30 min ago");
  });

  it("follows the real clock in a live workspace, and moves on", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2027-03-01T12:00:00Z"));
    renderWithIntl(
      <ClockProvider live>
        <Probe since="2027-03-01T11:55:00Z" />
      </ClockProvider>,
    );
    expect(screen.getByTestId("now")).toHaveTextContent("2027-03-01T12:00:00.000Z");
    expect(screen.getByTestId("ago")).toHaveTextContent("5 min ago");
    act(() => vi.advanceTimersByTime(60_000));
    expect(screen.getByTestId("ago")).toHaveTextContent("6 min ago");
  });

  it("uses the pinned now outside a workspace shell", () => {
    renderWithIntl(<Probe since="2026-10-12T15:40:00Z" />);
    expect(screen.getByTestId("ago")).toHaveTextContent("1 h ago");
  });
});
