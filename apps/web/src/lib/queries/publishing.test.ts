import { describe, expect, it } from "vitest";
import type { StudioListing } from "@/lib/api/gen/types.gen";
import { listingPoll, listingsPoll } from "./publishing";

const listing = (status: StudioListing["latest"]["status"]) => ({ latest: { status } }) as StudioListing;

describe("publishing polls", () => {
  it("reads a listing again every few seconds while its newest version is being checked", () => {
    expect(listingPoll(listing("checking"))).toBe(5_000);
    expect(listingPoll(listing("in_review"))).toBe(false);
    expect(listingPoll(undefined)).toBe(false);
  });

  it("reads the list again while any listing is being checked", () => {
    expect(listingsPoll([listing("approved"), listing("checking")])).toBe(5_000);
    expect(listingsPoll([listing("approved"), listing("checks_failed")])).toBe(false);
    expect(listingsPoll(undefined)).toBe(false);
  });
});
