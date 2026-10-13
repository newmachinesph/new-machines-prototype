import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getMeQueryKey } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { Me } from "@/lib/api/gen/types.gen";
import { renderWithIntl } from "@/test/intl";
import { InvitationNotices } from "./invitation-notice";

const sdk = vi.hoisted(() => ({ accept: vi.fn(), decline: vi.fn(), getMe: vi.fn() }));
vi.mock("@/lib/api/gen/sdk.gen", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/gen/sdk.gen")>()),
  acceptInvitation: sdk.accept,
  declineInvitation: sdk.decline,
  getMe: sdk.getMe,
}));

const OWN: Me = {
  userId: "uid_ben",
  email: "ben@example.com",
  orgId: "org_ben",
  orgName: "Ben's workspace",
  role: "owner",
  workspace: "live",
  invitations: [{ orgId: "org_ana", orgName: "Ana's workspace", role: "member", invitedAt: "2026-10-13T09:00:00Z" }],
};
const JOINED: Me = { ...OWN, orgId: "org_ana", orgName: "Ana's workspace", role: "member", invitations: [] };

function setup(me: Me = OWN, locale?: "en" | "ja") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(getMeQueryKey(), me);
  qc.setQueryData(["runs-of-the-old-org"], ["run_1"]);
  renderWithIntl(
    <QueryClientProvider client={qc}>
      <InvitationNotices />
    </QueryClientProvider>,
    { locale },
  );
  return qc;
}

beforeEach(() => {
  sdk.accept.mockReset().mockResolvedValue({ data: JOINED });
  sdk.decline.mockReset().mockResolvedValue({ data: { ...OWN, invitations: [] } });
  sdk.getMe.mockReset().mockResolvedValue({ data: JOINED });
});

describe("InvitationNotices", () => {
  it("shows nothing without invitations", () => {
    setup({ ...OWN, invitations: [] });
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  });

  it("names the inviting workspace and the role", () => {
    setup();
    expect(screen.getByText("Ana's workspace invited you to join as Member")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Decline" })).toBeEnabled();
  });

  it("is translated into Japanese", () => {
    setup(OWN, "ja");
    expect(screen.getByText("Ana's workspaceからメンバーとして参加するよう招待されています")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "承認する" })).toBeInTheDocument();
  });

  it("accepting calls the endpoint and resets every cached query, since the org changes", async () => {
    const qc = setup();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(sdk.accept).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org_ana" } }));
    await waitFor(() => expect(qc.getQueryData(["runs-of-the-old-org"])).toBeUndefined());
    await waitFor(() => expect(qc.getQueryData<Me>(getMeQueryKey())?.orgId).toBe("org_ana"));
    expect(sdk.getMe).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument());
  });

  it("declining removes the notice and keeps the rest of the cache", async () => {
    const qc = setup();
    await userEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(sdk.decline).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org_ana" } }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Decline" })).not.toBeInTheDocument());
    expect(sdk.accept).not.toHaveBeenCalled();
    expect(qc.getQueryData(["runs-of-the-old-org"])).toEqual(["run_1"]);
    expect(qc.getQueryData<Me>(getMeQueryKey())?.orgId).toBe("org_ben");
  });

  it("shows the API's reason when answering fails, and keeps the buttons", async () => {
    sdk.accept.mockRejectedValue({ status: 404, code: "NOT_FOUND", detail: "There is no pending invitation." });
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(await screen.findByText("There is no pending invitation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled();
  });
});
