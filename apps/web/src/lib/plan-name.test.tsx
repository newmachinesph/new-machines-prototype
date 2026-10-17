import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Locale } from "@/i18n/locales";
import { IntlWrapper } from "@/test/intl";
import { usePlanName } from "./plan-name";

const planName = (plan: string | undefined, locale: Locale = "en") =>
  renderHook(() => usePlanName()(plan), {
    wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper>,
  }).result.current;

describe("usePlanName", () => {
  it("translates the plans the messages know, whatever their case", () => {
    expect(planName("Trial")).toBe("Trial");
    expect(planName("trial", "ja")).toBe("トライアル");
    expect(planName("Pro", "ja")).toBe("Pro");
  });

  it("passes an unknown plan through and gives nothing for none", () => {
    expect(planName("Enterprise", "ja")).toBe("Enterprise");
    expect(planName(undefined)).toBeUndefined();
  });
});
