import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Locale } from "@/i18n/locales";
import { IntlWrapper } from "@/test/intl";
import { useRegionName } from "./region-name";

const regionName = (code: string, locale: Locale = "en") =>
  renderHook(() => useRegionName()(code), {
    wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper>,
  }).result.current;

describe("useRegionName", () => {
  it("names the platform's regions as Settings does, in each language", () => {
    expect(regionName("asia-south1")).toBe("Mumbai (asia-south1)");
    expect(regionName("asia-south1", "ja")).toBe("ムンバイ（asia-south1）");
    expect(regionName("asia-northeast1", "ja")).toBe("東京（asia-northeast1）");
  });

  it("shows a code the platform does not run in as it is", () => {
    expect(regionName("europe-west1", "ja")).toBe("europe-west1");
  });
});
