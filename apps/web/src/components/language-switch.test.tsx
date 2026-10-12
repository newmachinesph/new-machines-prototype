import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { LanguageSwitch } from "./language-switch";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const cookies = () => document.cookie.split("; ");

describe("LanguageSwitch", () => {
  beforeEach(() => {
    document.cookie = "NEXT_LOCALE=; path=/; max-age=0";
    refresh.mockClear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("marks the active language", () => {
    renderWithIntl(<LanguageSwitch />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "日本語" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "false");
  });

  it("writes the cookie and refreshes the server render", async () => {
    renderWithIntl(<LanguageSwitch />);
    await userEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(cookies()).toContain("NEXT_LOCALE=ja");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("adds the secure flag only on https", async () => {
    const write = vi.spyOn(document, "cookie", "set");
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, protocol: "https:" } as Location);
    renderWithIntl(<LanguageSwitch />);
    await userEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(write).toHaveBeenCalledWith(expect.stringContaining("; secure"));
  });

  it("omits the secure flag on http", async () => {
    const write = vi.spyOn(document, "cookie", "set");
    renderWithIntl(<LanguageSwitch />);
    await userEvent.click(screen.getByRole("button", { name: "日本語" }));
    expect(write).toHaveBeenCalledWith(expect.not.stringContaining("secure"));
  });
});
