import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import { NewTenantDialog } from "./new-tenant-dialog";

const create = vi.hoisted(() => vi.fn());
// A plain wrapper: a rejecting vi.fn leaves its own unhandled copy of the rejection and fails the test.
const failWith = vi.hoisted(() => ({ error: null as Error | null }));
vi.mock("@/lib/queries/tenants", () => ({
  useCreateTenant: () => ({
    mutateAsync: (arg: unknown) => (failWith.error ? Promise.reject(failWith.error) : create(arg)),
  }),
}));

beforeEach(() => {
  create.mockReset();
  failWith.error = null;
});

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, cap: string) {
  await user.type(screen.getByLabelText("Company name"), "Acme Corp");
  await user.type(screen.getByLabelText("Short name"), "Acme");
  await user.type(screen.getByLabelText("Owner email"), "owner@acme.test");
  await user.clear(screen.getByLabelText("Monthly spend cap (USD)"));
  await user.type(screen.getByLabelText("Monthly spend cap (USD)"), cap);
  await user.type(screen.getByLabelText("Reason"), "Signed order form");
  await user.click(screen.getByRole("button", { name: "Create tenant" }));
}

const renderDialog = (onOpenChange = vi.fn()) =>
  render(
    <UiProviders>
      <NewTenantDialog open onOpenChange={onOpenChange} />
    </UiProviders>,
  );

describe("NewTenantDialog submit", () => {
  it("sends the cap in minor units and closes on success", async () => {
    create.mockResolvedValue({ name: "Acme Corp" });
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderDialog(onOpenChange);
    await fillAndSubmit(user, "250.10");
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create.mock.calls[0][0].body).toMatchObject({
      name: "Acme Corp",
      country: "US",
      ownerEmail: "owner@acme.test",
      monthlyCapMinor: 25010,
      trialDays: 14,
      reason: "Signed order form",
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("shows an API error inline and stays open", async () => {
    failWith.error = new ApiError(409, "SLUG_TAKEN", "That short name is already taken.");
    const onOpenChange = vi.fn();
    const user = userEvent.setup();
    renderDialog(onOpenChange);
    await fillAndSubmit(user, "500");
    expect(await screen.findByText("That short name is already taken.")).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("blocks a malformed cap before calling the API", async () => {
    const user = userEvent.setup();
    renderDialog();
    await fillAndSubmit(user, "1e3");
    expect(await screen.findByText(/up to two decimals/)).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });
});
