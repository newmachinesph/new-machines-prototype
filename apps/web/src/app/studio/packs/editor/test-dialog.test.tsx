import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { TestDialog } from "./test-dialog";

const mocks = vi.hoisted(() => ({ test: { mutate: vi.fn(), isPending: false }, push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn() }) }));
vi.mock("@/lib/queries/me", () => ({ useOrgId: () => "org_a1" }));
vi.mock("@/lib/queries/studio", () => ({ useTestStudioPack: () => mocks.test }));

const FIELDS = [{ name: "as_of", label: "As of", type: "date" as const, required: true }];

/** Opens the dialog on the saved Overdue pack, fills the start form and starts the run; returns the mutate handlers. */
async function started() {
  renderWithIntl(<TestDialog packKey="org-a1--overdue" dirty={false} inputFields={FIELDS} />);
  await userEvent.click(screen.getByRole("button", { name: "Test in sandbox" }));
  fireEvent.change(screen.getByLabelText("As of"), { target: { value: "2026-10-01" } });
  await userEvent.click(screen.getByRole("button", { name: "Start the test run" }));
  return mocks.test.mutate.mock.calls[0];
}

describe("TestDialog", () => {
  beforeEach(() => {
    mocks.test.mutate.mockReset();
    mocks.push.mockReset();
  });

  it("waits until the changes are saved, because the sandbox runs the saved version", () => {
    renderWithIntl(<TestDialog packKey="org-a1--overdue" dirty inputFields={FIELDS} />);
    expect(screen.getByRole("button", { name: "Test in sandbox" })).toBeDisabled();
    expect(screen.getByText("Save your changes to test them.")).toBeInTheDocument();
  });

  it("waits until a new pack is saved", () => {
    renderWithIntl(<TestDialog dirty inputFields={FIELDS} />);
    expect(screen.getByRole("button", { name: "Test in sandbox" })).toBeDisabled();
    expect(screen.getByText("Save the pack to test it.")).toBeInTheDocument();
  });

  it("starts a sandbox test run with the start form's values and opens it", async () => {
    const [vars, handlers] = await started();
    expect(screen.getByText("Sandbox data")).toBeInTheDocument();
    expect(
      screen.getByText("Runs the saved version on sandbox data. Agent spend counts toward your monthly cap."),
    ).toBeInTheDocument();
    expect(vars).toEqual({
      path: { org_id: "org_a1", key: "org-a1--overdue" },
      body: { input: { as_of: "2026-10-01" } },
    });
    act(() => handlers.onSuccess({ id: "run_9" }));
    expect(mocks.push).toHaveBeenCalledWith("/app/runs/run_9");
  });

  it("sends a budget in cents when one is given", async () => {
    renderWithIntl(<TestDialog packKey="org-a1--overdue" dirty={false} inputFields={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Test in sandbox" }));
    fireEvent.change(screen.getByLabelText("Most this test may spend (USD)"), { target: { value: "12.5" } });
    await userEvent.click(screen.getByRole("button", { name: "Start the test run" }));
    expect(mocks.test.mutate.mock.calls[0][0].body).toEqual({ input: {}, budgetMinor: 1250 });
  });

  it("explains each way the API can refuse a test run, in the dialog", async () => {
    const [, handlers] = await started();
    const refusal = (status: number, code: string, detail: string, issues?: unknown[]) =>
      act(() => handlers.onError(new ApiError(status, code, detail, issues as never)));
    refusal(422, "BUDGET_REQUIRED", "Set a budget for this test run.");
    expect(screen.getByRole("alert")).toHaveTextContent("The test run did not start");
    expect(screen.getByRole("alert")).toHaveTextContent(/Enter a budget for this test/);
    refusal(422, "BUDGET_TOO_HIGH", "The budget can be at most $15 for this pack.");
    expect(screen.getByRole("alert")).toHaveTextContent(/above the pack's maximum/);
    expect(screen.getByRole("alert")).toHaveTextContent("The budget can be at most $15 for this pack.");
    refusal(422, "INVALID_INPUT", "The input is not valid. As of: must be a date.", [
      { kind: "input", key: "", path: "as_of", message: "As of must be a date." },
    ]);
    expect(screen.getByRole("alert")).toHaveTextContent("The input is not valid. As of: must be a date.");
    expect(screen.getByRole("alert")).toHaveTextContent("As of must be a date.");
    refusal(409, "SANDBOX_UNAVAILABLE", "Test runs need the platform's sandbox connectors.");
    expect(screen.getByRole("alert")).toHaveTextContent(/sandbox connectors/);
    refusal(409, "SPEND_CAP", "The monthly spend cap is reached.");
    expect(screen.getByRole("alert")).toHaveTextContent(/monthly spend cap/);
    expect(screen.getByRole("link", { name: "See usage" })).toHaveAttribute("href", "/app/usage");
    refusal(409, "PLATFORM_PAUSED", "New Machines is paused for maintenance.");
    expect(screen.getByRole("alert")).toHaveTextContent("New Machines is paused for maintenance.");
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("forgets a refusal when the dialog is opened again", async () => {
    const [, handlers] = await started();
    act(() => handlers.onError(new ApiError(422, "BUDGET_REQUIRED", "Set a budget for this test run.")));
    expect(screen.getByRole("alert")).toHaveTextContent(/Enter a budget/);
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Test in sandbox" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("speaks Japanese", async () => {
    renderWithIntl(<TestDialog packKey="org-a1--overdue" dirty={false} inputFields={FIELDS} />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "サンドボックスでテスト" }));
    expect(screen.getByRole("button", { name: "テスト実行を開始" })).toBeInTheDocument();
  });
});
