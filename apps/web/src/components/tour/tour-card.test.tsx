import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { TourCard } from "./tour-card";

function show(currentStep: number, totalSteps = 6, locale: "en" | "ja" = "en") {
  const props = {
    step: { title: "Runs", content: "Every run, with its status and spend." },
    currentStep,
    totalSteps,
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipTour: vi.fn(),
    arrow: <svg data-testid="arrow" />,
  };
  renderWithIntl(<TourCard {...props} />, { locale });
  return props;
}

describe("TourCard", () => {
  it("shows the step's title, body and place in the tour", () => {
    show(1);
    expect(screen.getByRole("dialog", { name: "Runs" })).toBeInTheDocument();
    expect(screen.getByText("Every run, with its status and spend.")).toBeInTheDocument();
    expect(screen.getByText("Step 2 of 6")).toBeInTheDocument();
    expect(screen.getByTestId("arrow")).toBeInTheDocument();
  });

  it("hides Back on the first step and moves focus to Next", () => {
    show(0);
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toHaveFocus();
  });

  it("goes back and on from a middle step", async () => {
    const props = show(2);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(props.prevStep).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(props.nextStep).toHaveBeenCalledTimes(1);
  });

  it("ends with Done on the last step", async () => {
    const props = show(5);
    expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(props.nextStep).toHaveBeenCalledTimes(1);
  });

  it("skips the tour", async () => {
    const props = show(1);
    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(props.skipTour).toHaveBeenCalledTimes(1);
  });

  it("is a modal dialog whose Tab and Shift+Tab stay among its buttons", async () => {
    show(2);
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    const skip = screen.getByRole("button", { name: "Skip tour" });
    const back = screen.getByRole("button", { name: "Back" });
    const next = screen.getByRole("button", { name: "Next" });
    expect(next).toHaveFocus();
    await userEvent.tab();
    expect(skip).toHaveFocus();
    await userEvent.tab();
    expect(back).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(skip).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(next).toHaveFocus();
  });

  it("hides the pointer arrow from assistive tech", () => {
    show(1);
    expect(screen.getByTestId("arrow").parentElement).toHaveAttribute("aria-hidden", "true");
  });

  it("opens a new dialog for each step, with focus moved into it, so the step is announced", () => {
    const props = {
      step: { title: "Runs", content: "Every run." },
      totalSteps: 6,
      nextStep: vi.fn(),
      prevStep: vi.fn(),
      skipTour: vi.fn(),
      arrow: <svg />,
    };
    const { rerender } = renderWithIntl(<TourCard {...props} currentStep={1} />);
    const before = screen.getByRole("dialog");
    rerender(<TourCard {...props} step={{ title: "Approvals", content: "Waits for you." }} currentStep={2} />);
    const after = screen.getByRole("dialog", { name: "Approvals" });
    expect(after).not.toBe(before);
    expect(before).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toHaveFocus();
  });

  it("speaks Japanese", () => {
    show(5, 6, "ja");
    expect(screen.getByText("ステップ 6/6")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完了" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "戻る" })).toBeInTheDocument();
  });
});
