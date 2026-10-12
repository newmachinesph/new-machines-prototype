import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { ServiceStatus } from "@/lib/api/gen/types.gen";

vi.mock("@/lib/queries/health", () => ({
  useDeclareIncident: () => ({ mutateAsync: vi.fn().mockResolvedValue({ title: "Latency" }) }),
}));

import { DeclareIncident } from "./declare-incident";

const services = [{ key: "api", name: "API" }] as ServiceStatus[];

function Harness() {
  const [open, setOpen] = useState(false);
  return <DeclareIncident open={open} onOpenChange={setOpen} services={services} canWrite />;
}

describe("DeclareIncident", () => {
  it("starts empty again each time it is reopened", async () => {
    const user = userEvent.setup();
    render(
      <UiProviders>
        <Harness />
      </UiProviders>,
    );
    await user.click(screen.getByRole("button", { name: "Declare incident" }));
    let dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Title"), "Latency");
    await user.click(within(dialog).getByRole("checkbox", { name: "API" }));
    await user.type(within(dialog).getByLabelText("Reason"), "Spike seen");
    await user.click(within(dialog).getByRole("button", { name: "Declare incident" }));
    await vi.waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Declare incident" }));
    dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByLabelText("Title")).toHaveValue("");
    expect(within(dialog).getByRole("checkbox", { name: "API" })).not.toBeChecked();
  });
});
