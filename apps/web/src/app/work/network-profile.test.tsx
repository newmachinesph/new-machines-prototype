import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { isComplete, NetworkProfilePanel, splitList } from "./network-profile";

const OFF = { enabled: false, suspended: false, name: "Nina Park", languages: [] as string[], skills: [] as string[] };
const state = vi.hoisted(() => ({ profile: undefined as unknown }));
const mutate = vi.hoisted(() => vi.fn());

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/tasks", () => ({
  useReviewerProfile: () => ({ data: state.profile }),
  useUpdateReviewerProfile: () => ({ mutate, isPending: false }),
}));

beforeEach(() => {
  state.profile = { ...OFF };
  mutate.mockClear();
});

describe("splitList", () => {
  it("splits on commas and drops blanks", () => {
    expect(splitList(" English, Tagalog ,, ")).toEqual(["English", "Tagalog"]);
  });
});

describe("isComplete", () => {
  it("needs a name and a language or a skill", () => {
    expect(isComplete({ name: "Nina", languages: [], skills: [] })).toBe(false);
    expect(isComplete({ name: " ", languages: ["English"], skills: [] })).toBe(false);
    expect(isComplete({ name: "Nina", languages: [], skills: ["Refunds"] })).toBe(true);
  });
});

describe("NetworkProfilePanel", () => {
  it("asks for the profile before turning on, then saves it with the switch on", async () => {
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(screen.getByRole("dialog", { name: "Your reviewer profile" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Languages"), "English, Tagalog");
    await userEvent.type(screen.getByLabelText("Skills"), "Reconciliation");
    expect(within(screen.getByRole("dialog")).queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save profile" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save and start reviewing" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: true, name: "Nina Park", languages: ["English", "Tagalog"], skills: ["Reconciliation"] } },
      expect.anything(),
    );
  });

  it("only saves the profile from Edit profile, leaving reviewing as it is", async () => {
    state.profile = { ...OFF, enabled: true, skills: ["Refunds"] };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("button", { name: "Edit profile" }));
    expect(within(screen.getByRole("dialog")).queryByRole("checkbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: true, name: "Nina Park", languages: [], skills: ["Refunds"] } },
      expect.anything(),
    );
  });

  it("turns on at once when the profile is already complete", async () => {
    state.profile = { ...OFF, skills: ["Refunds"] };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: true, name: "Nina Park", languages: [], skills: ["Refunds"] } },
      expect.anything(),
    );
  });

  it("does not save a profile without a name", async () => {
    state.profile = { ...OFF, name: "" };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(screen.getByRole("button", { name: "Save and start reviewing" })).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();
  });

  it("turns it off and keeps the profile", async () => {
    state.profile = { ...OFF, enabled: true, languages: ["English"], skills: ["Refunds"] };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Review for the network" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: false, name: "Nina Park", languages: ["English"], skills: ["Refunds"] } },
      expect.anything(),
    );
  });

  it("edits the profile from a button, with examples, without touching the switch", async () => {
    state.profile = { ...OFF, languages: ["English"] };
    renderWithIntl(<NetworkProfilePanel />);
    await userEvent.click(screen.getByRole("button", { name: "Edit profile" }));
    const skills = screen.getByLabelText("Skills");
    expect(skills).toHaveAccessibleDescription(
      "Separate with commas, for example Reconciliation, Refunds, Exception review",
    );
    await userEvent.type(skills, "Refunds, Exception review");
    await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
    expect(mutate).toHaveBeenCalledWith(
      { body: { enabled: false, name: "Nina Park", languages: ["English"], skills: ["Refunds", "Exception review"] } },
      expect.anything(),
    );
  });

  it("says when New Machines has paused the user's network reviews", () => {
    state.profile = { ...OFF, enabled: true, suspended: true };
    renderWithIntl(<NetworkProfilePanel />);
    expect(screen.getByText(/New Machines has paused your network reviews/)).toBeInTheDocument();
  });

  it("labels network pay as simulated", () => {
    renderWithIntl(<NetworkProfilePanel />);
    expect(screen.getByText(/Pay is simulated: no money moves\./)).toBeInTheDocument();
  });

  it("is translated", async () => {
    renderWithIntl(<NetworkProfilePanel />, { locale: "ja" });
    expect(screen.getByRole("checkbox", { name: "ネットワークでレビューする" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "プロフィールを編集" }));
    expect(screen.getByRole("button", { name: "プロフィールを保存" })).toBeInTheDocument();
  });
});
