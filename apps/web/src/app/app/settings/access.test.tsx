import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { MembersSection, TokensSection, maskedToken } from "./access";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const data = vi.hoisted(() => ({ demo: false, tokens: [] as unknown[], members: [] as unknown[] }));
const mutations = vi.hoisted(() => ({ create: vi.fn(), invite: vi.fn() }));
const toast = vi.hoisted(() => vi.fn());

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo, useOrgId: () => "org_new" }));
vi.mock("@/lib/queries/workspace", () => ({
  useMembers: () => ok(data.members),
  useInvite: () => ({ mutate: mutations.invite, isPending: false }),
  useTokens: () => ok(data.tokens),
  useCreateToken: () => ({ mutate: mutations.create, isPending: false }),
  useRevokeToken: () => ({ mutate: vi.fn() }),
}));

const token = (prefix: string | undefined, last4: string) => ({
  id: "tok_1",
  name: "Team assistant",
  last4,
  prefix,
  scopes: ["runs:read"],
  createdAt: "2026-10-12T10:00:00Z",
  expiresAt: "2026-11-11T10:00:00Z",
  lastUsed: "",
});

describe("maskedToken", () => {
  it("shows the prefix, a hidden middle and the last four when known", () => {
    expect(maskedToken({ prefix: "nm_pat_AbCd", last4: "wxyz" })).toBe("nm_pat_AbCd••••wxyz");
    expect(maskedToken({ prefix: "nm_pat_AbCd", last4: "" })).toBe("nm_pat_AbCd••••");
    expect(maskedToken({ last4: "9f2c" })).toBe("nm_pat_••••9f2c");
  });
});

describe("TokensSection", () => {
  beforeEach(() => {
    data.demo = false;
    data.tokens = [];
    mutations.create.mockReset();
  });

  it("points an empty list at creating a token, without naming any vendor", () => {
    renderWithIntl(<TokensSection />);
    expect(screen.getByText("No tokens. Create one to connect an AI tool.")).toBeInTheDocument();
    expect(screen.queryByText(/Gemini|Antigravity/)).not.toBeInTheDocument();
  });

  it("lists a token by its prefix and last four", () => {
    data.tokens = [token("nm_pat_AbCd", "")];
    renderWithIntl(<TokensSection />);
    expect(screen.getByText("nm_pat_AbCd••••")).toBeInTheDocument();
  });

  const createOne = async () => {
    mutations.create.mockImplementation((_vars, opts) =>
      opts.onSuccess({ token: token("nm_pat_AbCd", "wxyz"), secret: "nm_pat_AbCdSECRETwxyz" }),
    );
    renderWithIntl(<TokensSection />);
    await userEvent.click(screen.getByRole("button", { name: "Create token" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Team assistant");
    await userEvent.click(screen.getAllByRole("button", { name: "Create token" }).at(-1)!);
    return screen.findByText("nm_pat_AbCdSECRETwxyz");
  };

  it("shows the new token's secret once, with focus on Copy", async () => {
    expect(await createOne()).toBeInTheDocument();
    expect(screen.getByText(/only time the full token is shown/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy" })).toHaveFocus());
  });

  it("copies the secret and announces it", async () => {
    await createOne();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("nm_pat_AbCdSECRETwxyz");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(screen.getAllByText("Copied").some((el) => el.getAttribute("aria-live") === "polite")).toBe(true);
  });

  it("selects the secret for copying by hand when there is no clipboard", async () => {
    await createOne();
    toast.mockReset();
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(window.getSelection()?.toString()).toBe("nm_pat_AbCdSECRETwxyz");
    expect(toast).toHaveBeenCalledWith("Could not copy the token", expect.stringMatching(/selected/), "blocked");
  });
});

describe("MembersSection", () => {
  beforeEach(() => {
    data.members = [];
  });

  it("lists a member by email, without the API's sign-in status word", () => {
    data.members = [
      { name: "Ana Reyes", email: "ana@example.com", role: "Owner", via: "Signed in" },
      { name: "sam@example.com", email: "sam@example.com", role: "Member", via: "Invite link", pending: true },
    ];
    renderWithIntl(<MembersSection />);
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    expect(screen.queryByText(/signs in with|Signed in/)).not.toBeInTheDocument();
    expect(screen.getByText("Invite sent, not accepted yet")).toBeInTheDocument();
  });

  it("invites into the signed-in user's org", async () => {
    renderWithIntl(<MembersSection />);
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Email" }), "sam@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
    expect(mutations.invite).toHaveBeenCalledWith(
      { path: { org_id: "org_new" }, body: { email: "sam@example.com", role: "Member" } },
      expect.anything(),
    );
  });
});
