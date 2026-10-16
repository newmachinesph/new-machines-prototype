import { afterEach, describe, expect, it, vi } from "vitest";
import { cardRoom, DEFAULT_CARD_ROOM, fitsWithCard, scrollToFit, TOP_CLEARANCE } from "./fit";

const ROOM = 300;
const desktop = { width: 1440, height: 900, scrollY: 0, docHeight: 3000, cardRoom: ROOM };
const phone = { width: 390, height: 844, scrollY: 0, docHeight: 5000, cardRoom: ROOM };
const box = (top: number, height: number, left = 300, width = 600) => ({
  top,
  bottom: top + height,
  left,
  right: left + width,
});

describe("scrollToFit", () => {
  it("leaves a target alone when it and a card below it already show", () => {
    expect(scrollToFit("bottom", box(200, 300), desktop)).toBe(0);
  });

  it("scrolls a target up under the top bar when its card would fall past the bottom", () => {
    // The run's steps panel at 1440: in view, but the card below it would end past 900px.
    expect(scrollToFit("bottom", box(297, 500), desktop)).toBe(297 - TOP_CLEARANCE);
  });

  it("uses the room the card on screen needs", () => {
    // 200 + 300 + 300 = 800 fits a 300px card, not a 420px one.
    expect(scrollToFit("bottom", box(200, 300), desktop)).toBe(0);
    expect(scrollToFit("bottom", box(200, 300), { ...desktop, cardRoom: 420 })).toBe(200 - TOP_CLEARANCE);
  });

  it("scrolls a target down from under the top bar", () => {
    expect(scrollToFit("bottom", box(40, 50), desktop)).toBe(40 - TOP_CLEARANCE);
  });

  it("scrolls a target whose card sits above it to near the bottom of the window", () => {
    const r = box(100, 120);
    expect(scrollToFit("top", r, { ...desktop, scrollY: 1000 })).toBe(r.bottom - (900 - 16));
  });

  it("centres a target whose card sits beside it", () => {
    const r = box(1200, 200, 900, 400);
    expect(scrollToFit("left", r, desktop)).toBe(1300 - (TOP_CLEARANCE + 900) / 2);
    expect(scrollToFit("left", box(300, 200, 900, 400), desktop)).toBe(0);
  });

  it("treats a left card with no room beside its target as a card below it, as the library does", () => {
    // On a phone a full-width panel has no room on either side.
    const r = box(600, 60, 16, 358);
    expect(scrollToFit("left", r, phone)).toBe(600 - TOP_CLEARANCE);
  });

  it("puts a card above a target near the end of the document below it instead when there is no room above", () => {
    expect(scrollToFit("top", box(20, 60), { ...desktop, docHeight: 900 })).toBe(20 - TOP_CLEARANCE);
  });
});

describe("fitsWithCard", () => {
  it("says whether a target and its card fit under the top bar together", () => {
    expect(fitsWithCard(900 - TOP_CLEARANCE - ROOM, 900, ROOM)).toBe(true);
    expect(fitsWithCard(900 - TOP_CLEARANCE - ROOM + 1, 900, ROOM)).toBe(false);
  });
});

describe("cardRoom", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("measures the card on screen and adds its gap", () => {
    const card = document.createElement("div");
    card.dataset.name = "nextstep-card";
    vi.spyOn(card, "offsetHeight", "get").mockReturnValue(250);
    document.body.append(card);
    expect(cardRoom()).toBe(283);
  });

  it("keeps a generous room while no card is on screen", () => {
    expect(cardRoom()).toBe(DEFAULT_CARD_ROOM);
  });
});
