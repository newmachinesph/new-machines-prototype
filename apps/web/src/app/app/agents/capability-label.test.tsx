import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Locale } from "@/i18n/locales";
import { IntlWrapper } from "@/test/intl";
import { humaniseCapability, useCapabilityLabel } from "./capability-label";

const label = (locale: Locale) =>
  renderHook(useCapabilityLabel, {
    wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper>,
  }).result.current;

describe("useCapabilityLabel", () => {
  it("labels a known id in the interface language", () => {
    expect(label("en")("finance.collections_draft")).toBe("Collections reminder drafts");
    expect(label("ja")("finance.collections_draft")).toBe("督促文の下書き");
    expect(label("ja")("customer.support")).toBe("カスタマーサポート");
  });

  it("falls back to the id's own words in every language, never to the raw id", () => {
    expect(label("en")("team.triage")).toBe("Team triage");
    expect(label("ja")("team.triage")).toBe("Team triage");
  });
});

describe("humaniseCapability", () => {
  it("turns a dotted id into words", () => {
    expect(humaniseCapability("finance.collections")).toBe("Finance collections");
    expect(humaniseCapability("message.create_draft")).toBe("Message create draft");
    expect(humaniseCapability("drive.file.create")).toBe("Drive file create");
  });

  it("splits camel case and ignores stray separators", () => {
    expect(humaniseCapability("catalogRead")).toBe("Catalog read");
    expect(humaniseCapability("..orders-read")).toBe("Orders read");
  });
});
