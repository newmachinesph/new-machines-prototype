import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import messages from "../../messages/en.json";
import { useOutcomeLabel } from "./outcome-label";

const wrapper = ({ children }: { children: ReactNode }) => (
  <NextIntlClientProvider locale="en" messages={messages}>
    {children}
  </NextIntlClientProvider>
);

describe("useOutcomeLabel", () => {
  it("returns the same function across renders, so memos built on it hold", () => {
    const { result, rerender } = renderHook(() => useOutcomeLabel(), { wrapper });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });

  it("translates a known outcome and reads a route name as words", () => {
    const { result } = renderHook(() => useOutcomeLabel(), { wrapper });
    expect(result.current("granted")).toBe("Approved");
    expect(result.current("human_review")).toBe("Human review");
    expect(result.current(undefined)).toBeUndefined();
  });
});
