import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { NodeStatusPill, OutcomeRail, RunStatusPill } from "./ui";

describe("status labels", () => {
  it("reads run and node statuses from the messages", () => {
    renderWithIntl(
      <>
        <RunStatusPill status="WAITING_FOR_EVENT" />
        <NodeStatusPill status="TIMED_OUT" />
      </>,
    );
    expect(screen.getByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("switches to Japanese with the locale", () => {
    renderWithIntl(<RunStatusPill status="COMPLETED" />, { locale: "ja" });
    expect(screen.getByText("完了")).toBeInTheDocument();
  });

  it("names each outcome stage and its state", () => {
    renderWithIntl(
      <OutcomeRail
        compact
        stages={{ executed: "done", verified: "pending", accepted: "not_required", settlement: "blocked" }}
      />,
    );
    expect(screen.getByText("Executed: Yes")).toBeInTheDocument();
    expect(screen.getByText("Settlement eligible: On hold")).toBeInTheDocument();
  });
});
