import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { mergeMessages } from "@/i18n/locales";
import { renderWithIntl } from "@/test/intl";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";
import { RunRecord } from "./run-record";

// The record is an async server component; give it the same translators the server would.
vi.mock("next-intl/server", async () => {
  const { createTranslator } = await import("next-intl");
  const messages = mergeMessages(en, ja);
  return {
    getLocale: async () => "ja",
    getTranslations: async (namespace: string) =>
      createTranslator({ locale: "ja", messages, namespace: namespace as never }),
  };
});

vi.stubGlobal(
  "IntersectionObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

describe("landing run record in Japanese", () => {
  it("translates headings and the legend, but keeps the run's record lines in English", async () => {
    renderWithIntl(await RunRecord(), { locale: "ja" });
    expect(screen.getByRole("heading", { name: "Harbor & Pine の昨日の照合" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "実行済み" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "精算済み" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "この実行を開く" })).toBeInTheDocument();
    expect(screen.getByLabelText("誰が何をしたか")).toHaveTextContent("人間のレビュアー");
    expect(screen.queryByText("Person")).not.toBeInTheDocument();
    expect(screen.getByText("Matched 28 orders. Flagged 3 that did not add up.")).toBeInTheDocument();
    expect(screen.getByText("$9.40 charged. $7.50 paid to the reviewer.")).toBeInTheDocument();
  });
});
