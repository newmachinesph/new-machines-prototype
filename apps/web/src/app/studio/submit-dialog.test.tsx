import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { InputField, StudioListingDetail } from "@/lib/api/gen/types.gen";
import { renderWithIntl } from "@/test/intl";
import { SubmitButton, SubmitDialog } from "./submit-dialog";

const mocks = vi.hoisted(() => ({
  submit: { mutate: vi.fn(), isPending: false },
  publisher: {
    data: { enabled: true } as { enabled: boolean } | undefined,
    isPending: false,
    isError: false,
    error: null as unknown,
  },
  role: "owner",
  /** What a read of the submitted listing answers; undefined until it has. */
  live: undefined as StudioListingDetail | undefined,
  listings: [] as { id: string; key: string }[],
  runStatus: "RUNNING" as string,
}));
vi.mock("@/lib/queries/runs", () => ({
  useRun: () => ({ data: { status: mocks.runStatus } }),
}));
vi.mock("@/lib/queries/me", () => ({
  useOrgId: () => "org_a1",
  useMe: () => ({ data: { role: mocks.role } }),
}));
vi.mock("@/lib/queries/submissions", () => ({
  useSubmitListing: () => mocks.submit,
}));
vi.mock("@/lib/queries/publisher", () => ({ usePublisher: () => mocks.publisher }));
vi.mock("@/lib/queries/publishing", () => ({
  useStudioListing: () => ({ data: mocks.live }),
  useStudioListings: () => ({ data: mocks.listings }),
}));

const FIELDS: InputField[] = [{ name: "as_of", label: "As of", type: "date", required: true }];

const listing = (
  sandbox: "running" | "passed" | "failed",
  status: "checking" | "in_review" | "checks_failed",
): StudioListingDetail =>
  ({
    id: "lst_1",
    kind: "pack",
    key: "org-a1--overdue",
    name: "Overdue",
    status: "pending",
    price: { amountMinor: 50 },
    latest: {
      id: "ver_1",
      definitionVersion: 2,
      status,
      price: { amountMinor: 50 },
      checks: [
        { name: "definition", state: "passed", detail: "Definition is valid." },
        { name: "agents", state: "passed", detail: "Agents are public." },
        { name: "sandbox", state: sandbox, detail: "Sandbox test.", runId: "run_7" },
      ],
      submittedAt: "2026-10-16T00:00:00Z",
      submittedBy: "u1",
    },
    installs: 0,
    runs30d: 0,
    earningsMonth: { amountMinor: 0 },
  }) as StudioListingDetail;

const agentDialog = () =>
  renderWithIntl(<SubmitDialog kind="agent" keyName="org-a1--helper" name="Helper" open onClose={vi.fn()} />);
const packDialog = () =>
  renderWithIntl(
    <SubmitDialog kind="pack" keyName="org-a1--overdue" name="Overdue" inputFields={FIELDS} open onClose={vi.fn()} />,
  );

const submitPack = async () => {
  packDialog();
  await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
  await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
  await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
};

describe("SubmitDialog", () => {
  beforeEach(() => {
    mocks.submit.mutate.mockReset();
    mocks.publisher.data = { enabled: true };
    mocks.publisher.isPending = false;
    mocks.publisher.isError = false;
    mocks.role = "owner";
    mocks.live = undefined;
    mocks.runStatus = "RUNNING";
    mocks.listings = [];
  });

  it("without a publisher profile explains and links to Settings, with no form", () => {
    mocks.publisher.data = { enabled: false };
    agentDialog();
    expect(screen.getByText("Turn on publishing in Settings first.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/app/settings#publishing");
    expect(screen.queryByLabelText("Price per call")).not.toBeInTheDocument();
  });

  it("asks an agent for a price per call, previews the 80/20 split and sends minor units", async () => {
    agentDialog();
    await userEvent.type(screen.getByLabelText("Price per call"), "0.30");
    expect(screen.getByText("You get 80%, New Machines keeps 20%.")).toBeInTheDocument();
    expect(screen.getByText("$0.24 to you")).toBeInTheDocument();
    expect(screen.getByText("$0.24 to you").parentElement).toHaveTextContent("Simulated");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(mocks.submit.mutate.mock.calls[0][0]).toEqual({
      path: { org_id: "org_a1", key: "org-a1--helper" },
      body: { priceMinor: 30 },
    });
  });

  it("floors the publisher share to whole cents", async () => {
    agentDialog();
    await userEvent.type(screen.getByLabelText("Price per call"), "0.33");
    expect(screen.getByText("$0.26 to you")).toBeInTheDocument();
  });

  it("waits for the publisher profile instead of asking to turn publishing on", () => {
    mocks.publisher.data = undefined;
    mocks.publisher.isPending = true;
    agentDialog();
    expect(screen.queryByText("Turn on publishing in Settings first.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Price per call")).not.toBeInTheDocument();
  });

  it("says so when the publisher profile cannot be loaded", () => {
    mocks.publisher.data = undefined;
    mocks.publisher.isError = true;
    mocks.publisher.error = new ApiError(500, "BOOM", "Profile unavailable.");
    agentDialog();
    expect(screen.getByText("Profile unavailable.")).toBeInTheDocument();
    expect(screen.queryByText("Turn on publishing in Settings first.")).not.toBeInTheDocument();
  });

  it("asks a pack for a price per run, the sandbox input and an optional budget", async () => {
    packDialog();
    expect(screen.getByText(/A test that already completed for this version is reused/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Price per run"), "1.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("Budget for the test run"), "20");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(mocks.submit.mutate.mock.calls[0][0].body).toEqual({
      priceMinor: 150,
      input: { as_of: "2026-10-01" },
      budgetMinor: 2000,
    });
  });

  it("previews a price of 0 as no fee", async () => {
    agentDialog();
    await userEvent.type(screen.getByLabelText("Price per call"), "0");
    expect(screen.getByText("No fee")).toBeInTheDocument();
    expect(screen.queryByText("You get 80%, New Machines keeps 20%.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(mocks.submit.mutate.mock.calls[0][0].body).toEqual({ priceMinor: 0 });
  });

  it("shows the checks, the sandbox wait and the run link after a 201", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    packDialog();
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByText("Waiting for the sandbox run")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute("href", "/app/runs/run_7");
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.queryByText("Sent for review")).not.toBeInTheDocument();
  });

  it("tells the publisher when the check run waits for a reviewer, with a link to the run", async () => {
    mocks.runStatus = "WAITING_FOR_HUMAN";
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    await submitPack();
    expect(screen.getByText("The check is waiting for a reviewer in your workspace.")).toBeInTheDocument();
  });

  it("says nothing of a reviewer while the check run is simply running", async () => {
    mocks.runStatus = "RUNNING";
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    await submitPack();
    expect(screen.queryByText(/waiting for a reviewer/)).not.toBeInTheDocument();
  });

  it("ignores a cached listing read of an earlier version", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    const old = listing("failed", "checks_failed");
    old.latest.id = "ver_0";
    mocks.live = old;
    await submitPack();
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for the sandbox run");
  });

  it("says it was sent for review and links to the listing once the checks pass", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("passed", "in_review")));
    packDialog();
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByText("Sent for review")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the listing" })).toHaveAttribute("href", "/studio/publisher/lst_1");
  });

  it("shows the detail of a refused submission naming the private agents", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) =>
      h.onError(new ApiError(422, "PRIVATE_AGENTS", "These agents need to be listed first: Helper (not submitted).")),
    );
    packDialog();
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByText("These agents need to be listed first: Helper (not submitted).")).toBeInTheDocument();
  });

  it("lists each issue of an invalid definition", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) =>
      h.onError(
        new ApiError(422, "INVALID_DEFINITION", "The definition has problems.", [
          { kind: "step", key: "a", path: "steps/a", message: "Step a has no outcome." },
        ]),
      ),
    );
    agentDialog();
    await userEvent.type(screen.getByLabelText("Price per call"), "0.5");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByText("a: Step a has no outcome.")).toBeInTheDocument();
  });

  it("shows the problem detail of an open submission", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) =>
      h.onError(new ApiError(409, "SUBMISSION_OPEN", "A version of this is already waiting for review.")),
    );
    agentDialog();
    await userEvent.type(screen.getByLabelText("Price per call"), "0.5");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByText("A version of this is already waiting for review.")).toBeInTheDocument();
  });

  const submitPack = async () => {
    packDialog();
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
  };

  it("asks for the pack's sandbox input in its own group", () => {
    packDialog();
    const group = screen.getByRole("group", { name: "Input for the sandbox test" });
    expect(within(group).getByLabelText("As of")).toBeInTheDocument();
  });

  it("moves on from Waiting to Sent for review as the listing is read again", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    const view = packDialog();
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for the sandbox run");
    mocks.live = listing("passed", "in_review");
    view.rerender(
      <SubmitDialog kind="pack" keyName="org-a1--overdue" name="Overdue" inputFields={FIELDS} open onClose={vi.fn()} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Sent for review");
  });

  it("says when a check failed once the listing is read again", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    mocks.live = listing("failed", "checks_failed");
    await submitPack();
    expect(screen.getByRole("status")).toHaveTextContent("A check failed.");
    expect(screen.queryByText("Sent for review")).not.toBeInTheDocument();
  });

  it("keeps one status region from the form to the result, and moves focus to the result", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) => h.onSuccess(listing("running", "checking")));
    packDialog();
    const region = screen.getByRole("status");
    await userEvent.type(screen.getByLabelText("Price per run"), "0.5");
    await userEvent.type(screen.getByLabelText("As of"), "2026-10-01");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getAllByRole("status")).toEqual([region]);
    expect(screen.getByRole("heading", { name: "Automatic checks" })).toHaveFocus();
  });

  it("words a fixed refusal in the interface language", async () => {
    mocks.submit.mutate.mockImplementation((_v, h) =>
      h.onError(new ApiError(409, "SUBMISSION_OPEN", "A version of this is already waiting for review.")),
    );
    renderWithIntl(<SubmitDialog kind="agent" keyName="org-a1--helper" name="Helper" open onClose={vi.fn()} />, {
      locale: "ja",
    });
    await userEvent.type(screen.getByLabelText("1回の呼び出しあたりの手数料"), "0.5");
    await userEvent.click(screen.getByRole("button", { name: "審査に提出" }));
    expect(
      screen.getByText("このエージェントまたはパックには、審査を待っているバージョンがすでにあります。"),
    ).toBeInTheDocument();
  });

  it("links to the listing whose version is already waiting for review", async () => {
    mocks.listings = [{ id: "lst_9", key: "org-a1--overdue" }];
    mocks.submit.mutate.mockImplementation((_v, h) =>
      h.onError(new ApiError(409, "SUBMISSION_OPEN", "A version of this is already waiting for review.")),
    );
    await submitPack();
    expect(screen.getByRole("link", { name: "Open the listing" })).toHaveAttribute("href", "/studio/publisher/lst_9");
  });
});

describe("SubmitButton", () => {
  const button = (dirty: boolean) =>
    renderWithIntl(<SubmitButton kind="agent" keyName="org-a1--helper" name="Helper" dirty={dirty} />);

  beforeEach(() => {
    mocks.publisher.data = { enabled: true };
    mocks.publisher.isPending = false;
    mocks.publisher.isError = false;
    mocks.role = "owner";
  });

  it("is disabled with the hint while there are unsaved changes", () => {
    button(true);
    const b = screen.getByRole("button", { name: "Submit for review" });
    expect(b).toBeDisabled();
    expect(b).toHaveAccessibleDescription("Save your changes first");
  });

  it("opens the dialog for a saved definition", async () => {
    button(false);
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(screen.getByLabelText("Price per call")).toBeInTheDocument();
  });

  it("does not submit the form it sits in when the dialog submits", async () => {
    mocks.submit.mutate.mockReset();
    const spy = vi.fn((e: React.FormEvent) => e.preventDefault());
    renderWithIntl(
      <form onSubmit={spy}>
        <SubmitButton kind="agent" keyName="org-a1--helper" name="Helper" dirty={false} />
      </form>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    await userEvent.type(screen.getByLabelText("Price per call"), "0.5");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Submit for review" }));
    expect(mocks.submit.mutate).toHaveBeenCalled();
    expect(spy).not.toHaveBeenCalled();
  });

  it("is hidden from members", () => {
    mocks.role = "member";
    button(false);
    expect(screen.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument();
  });
});
