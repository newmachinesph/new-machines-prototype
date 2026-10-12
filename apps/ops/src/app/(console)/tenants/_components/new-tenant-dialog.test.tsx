import { describe, expect, it } from "vitest";
import { newTenantSchema } from "./new-tenant-dialog";

const valid = {
  name: "Acme",
  short: "Acme",
  plan: "Pro" as const,
  region: "us-central1",
  country: "US",
  ownerEmail: "o@acme.test",
  monthlyCapDollars: "500",
  trialDays: "14",
  reason: "Signed order form",
};

describe("newTenantSchema", () => {
  it("accepts a valid tenant", () => {
    expect(newTenantSchema.safeParse(valid).success).toBe(true);
  });
  it.each([
    ["country", "us"],
    ["country", "USA"],
    ["trialDays", "0"],
    ["trialDays", "91"],
    ["trialDays", "1.5"],
    ["monthlyCapDollars", "1e3"],
    ["monthlyCapDollars", "250.123"],
    ["monthlyCapDollars", "-5"],
    ["monthlyCapDollars", "abc"],
    ["ownerEmail", "nope"],
    ["reason", "  "],
  ])("rejects %s = %j", (key, value) => {
    expect(newTenantSchema.safeParse({ ...valid, [key]: value }).success).toBe(false);
  });
  it("accepts the $0 and $100,000 bounds and rejects beyond them", () => {
    expect(newTenantSchema.safeParse({ ...valid, monthlyCapDollars: "0" }).success).toBe(true);
    expect(newTenantSchema.safeParse({ ...valid, monthlyCapDollars: "100000" }).success).toBe(true);
    expect(newTenantSchema.safeParse({ ...valid, monthlyCapDollars: "100000.01" }).success).toBe(false);
    expect(newTenantSchema.safeParse({ ...valid, monthlyCapDollars: "0x10" }).success).toBe(false);
  });
});
