import { describe, expect, it } from "vitest";
import { humaniseCapability } from "./capability-label";

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
