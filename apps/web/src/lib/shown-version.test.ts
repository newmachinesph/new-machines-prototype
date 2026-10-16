import { describe, expect, it } from "vitest";
import { shownVersion } from "./shown-version";

const listing = { listingId: "lst_1", publisher: "Acme Labs", fee: { amountMinor: 0 }, feeUnit: "run" as const };

describe("shownVersion", () => {
  it("keeps a platform definition's own version", () => {
    expect(shownVersion({ version: "1.1.0" })).toBe("1.1.0");
  });

  it("shows a Studio-built definition by its definition version, not the 1.0.<n> the Studio writes", () => {
    expect(shownVersion({ version: "1.0.1", builtByTeam: true })).toBe("1");
    expect(shownVersion({ version: "1.0.12", builtByTeam: true })).toBe("12");
  });

  it("shows a listed definition by its approved version", () => {
    expect(shownVersion({ version: "1.0.3", listing: { ...listing, version: 2 } })).toBe("2");
  });

  it("keeps a team-built version the Studio did not write", () => {
    expect(shownVersion({ version: "2.4.0", builtByTeam: true })).toBe("2.4.0");
  });
});
