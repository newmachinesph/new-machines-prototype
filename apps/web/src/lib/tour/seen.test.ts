import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isSeen, markSeen, markStarted, reset, seen, seenKey, startedThisSession } from "./seen";
import { TOURS, type TourName } from "./tours";

const NAMES = Object.keys(TOURS) as TourName[];

/** A storage whose every call throws, as Safari's private mode once did. */
const throwing = {
  getItem: () => {
    throw new Error("denied");
  },
  setItem: () => {
    throw new Error("denied");
  },
  removeItem: () => {
    throw new Error("denied");
  },
};

describe("tour seen store", () => {
  beforeEach(() => {
    window.localStorage.clear();
    for (const name of NAMES) reset(name);
  });
  afterEach(() => vi.restoreAllMocks());

  it("keys each tour by name and version", () => {
    expect(seenKey("welcome")).toBe("nm.tour.welcome.v1");
    expect(seenKey("run")).toBe("nm.tour.run.v1");
  });

  it("is unseen until marked, then stores done in localStorage", () => {
    expect(isSeen("welcome")).toBe(false);
    markSeen("welcome");
    expect(isSeen("welcome")).toBe(true);
    expect(window.localStorage.getItem("nm.tour.welcome.v1")).toBe("done");
    expect(isSeen("studio")).toBe(false);
  });

  it("reads a tour finished in an earlier session", () => {
    window.localStorage.setItem("nm.tour.studio.v1", "done");
    expect(isSeen("studio")).toBe(true);
  });

  it("forgets a tour on reset", () => {
    markSeen("welcome");
    reset("welcome");
    expect(isSeen("welcome")).toBe(false);
    expect(window.localStorage.getItem("nm.tour.welcome.v1")).toBeNull();
  });

  it("never throws when storage does, and remembers the tour for the session", () => {
    expect(isSeen("welcome", throwing)).toBe(false);
    expect(() => markSeen("welcome", throwing)).not.toThrow();
    expect(isSeen("welcome", throwing)).toBe(true);
    expect(() => reset("welcome", throwing)).not.toThrow();
    expect(isSeen("welcome", throwing)).toBe(false);
  });

  it("copes when localStorage itself cannot be reached", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(isSeen("welcome")).toBe(false);
    expect(() => markSeen("welcome")).not.toThrow();
    expect(isSeen("welcome")).toBe(true);
  });

  it("remembers a tour that started this session apart from seen, until reset", () => {
    expect(startedThisSession("welcome")).toBe(false);
    markStarted("welcome");
    expect(startedThisSession("welcome")).toBe(true);
    expect(isSeen("welcome")).toBe(false);
    expect(startedThisSession("studio")).toBe(false);
    reset("welcome");
    expect(startedThisSession("welcome")).toBe(false);
  });

  it("exposes the store as one object", () => {
    seen.markSeen("studio");
    expect(seen.isSeen("studio")).toBe(true);
    seen.reset("studio");
    expect(seen.isSeen("studio")).toBe(false);
  });
});
