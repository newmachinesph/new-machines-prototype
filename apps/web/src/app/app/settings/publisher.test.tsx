import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { PublisherSection } from "./publisher";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const state = vi.hoisted(() => ({
  role: "owner",
  disablePending: false,
  publisher: { enabled: false } as unknown,
  error: undefined as Error | undefined,
}));
const save = vi.hoisted(() => vi.fn());
const disable = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => ok({ orgId: "org_new", role: state.role, workspace: "live" }),
  useOrgId: () => "org_new",
}));
vi.mock("@/lib/queries/publisher", () => ({
  usePublisher: () =>
    state.error
      ? { isPending: false, isError: true, error: state.error, data: undefined, refetch: vi.fn() }
      : ok(state.publisher),
  useSavePublisher: () => ({ mutate: save, isPending: false }),
  useDisablePublisher: () => ({ mutate: disable, isPending: state.disablePending }),
}));

const on = {
  enabled: true,
  simulated: true,
  profile: { name: "Acme Labs", description: "Finance agents", payoutNote: "IBAN 1234" },
};

describe("PublisherSection", () => {
  beforeEach(() => {
    state.role = "owner";
    state.disablePending = false;
    state.publisher = { enabled: false };
    state.error = undefined;
    save.mockReset();
    disable.mockReset();
    toast.mockReset();
  });

  it("when off shows the turn-on button and no profile", () => {
    renderWithIntl(<PublisherSection />);
    expect(screen.getByRole("heading", { name: "Publish to the marketplace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on publishing" })).toBeInTheDocument();
    expect(screen.queryByText("Acme Labs")).not.toBeInTheDocument();
  });

  it("saves the trimmed profile and toasts", async () => {
    const user = userEvent.setup();
    save.mockImplementation((_v, opts) => opts.onSuccess());
    renderWithIntl(<PublisherSection />);
    await user.click(screen.getByRole("button", { name: "Turn on publishing" }));
    await user.type(screen.getByLabelText("Publisher name"), "  Acme Labs ");
    await user.type(screen.getByLabelText("Description"), " Finance agents ");
    await user.type(screen.getByLabelText("Payout details"), " IBAN 1234 ");
    expect(screen.getByText("Simulated: no money moves")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][0]).toEqual({
      path: { org_id: "org_new" },
      body: { name: "Acme Labs", description: "Finance agents", payoutNote: "IBAN 1234" },
    });
    expect(toast).toHaveBeenCalledWith("Publishing is on.");
  });

  it("refuses a blank name", async () => {
    const user = userEvent.setup();
    renderWithIntl(<PublisherSection />);
    await user.click(screen.getByRole("button", { name: "Turn on publishing" }));
    await user.type(screen.getByLabelText("Publisher name"), "   ");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Enter a publisher name.")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("shows a server problem's detail", async () => {
    const user = userEvent.setup();
    save.mockImplementation((_v, opts) => opts.onError({ status: 422, code: "VALIDATION", detail: "Name is taken." }));
    renderWithIntl(<PublisherSection />);
    await user.click(screen.getByRole("button", { name: "Turn on publishing" }));
    await user.type(screen.getByLabelText("Publisher name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Name is taken.")).toBeInTheDocument();
  });

  it("when on shows the name and a simulated payout", () => {
    state.publisher = on;
    renderWithIntl(<PublisherSection />);
    expect(screen.getByText("Acme Labs")).toBeInTheDocument();
    expect(screen.getByText("IBAN 1234")).toBeInTheDocument();
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("asks before turning off", async () => {
    const user = userEvent.setup();
    state.publisher = on;
    disable.mockImplementation((_v, opts) => opts.onSuccess());
    renderWithIntl(<PublisherSection />);
    await user.click(screen.getByRole("button", { name: "Turn off publishing" }));
    expect(disable).not.toHaveBeenCalled();
    expect(screen.getByText(/Turning publishing off stops new submissions/)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Turn off publishing" });
    await user.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(disable).toHaveBeenCalledWith({ path: { org_id: "org_new" } }, expect.anything()));
    expect(toast).toHaveBeenCalledWith("Publishing is off.");
  });

  it("disables turning off while the request is pending", () => {
    state.publisher = on;
    state.disablePending = true;
    renderWithIntl(<PublisherSection />);
    expect(screen.getByRole("button", { name: "Turn off publishing" })).toBeDisabled();
  });

  it("is not shown to a member: only owners and admins see publishing", () => {
    state.role = "member";
    state.publisher = on;
    const { container } = renderWithIntl(<PublisherSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders in Japanese", () => {
    renderWithIntl(<PublisherSection />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "マーケットプレイスに公開" })).toBeInTheDocument();
  });

  it("shows a failed read inside the section with a retry, not instead of the page", () => {
    state.error = new Error("boom");
    renderWithIntl(<PublisherSection />);
    expect(screen.getByRole("heading", { name: "Publish to the marketplace" })).toBeInTheDocument();
    expect(screen.getByText("This could not load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
