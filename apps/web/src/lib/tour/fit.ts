import type { TourSide } from "./tours";

/** The shell's top bar (56px) and, below lg, the simulation strip under it. Nothing a tour shows goes under these. */
export const TOP_CLEARANCE = 88;
/** The space between a card and its target: the library's 25px offset and the card's caret. */
const CARD_GAP = 33;
/** Room kept for a card not yet on screen (before a tour starts): taller than any step's card, Japanese included. */
export const DEFAULT_CARD_ROOM = 300;
/** Room the tour library needs beside a target before it moves a left or right card above or below it instead. */
const SIDE_ROOM = 256;
/** Gap kept under a target whose card sits above it. */
const BOTTOM_GAP = 16;
/** Below this window width (Tailwind's `sm`) the card is a sheet along the bottom of the window, whatever a step's
 * side: a phone has no room beside a target, and a card below one would cover what comes next on the page. */
export const SHEET_MAX_WIDTH = 640;
/** The card itself (TourCard), which the sheet takes out of the library's container; else that container. */
const CARD_SELECTOR = "[data-tour-card]";
const CONTAINER_SELECTOR = '[data-name="nextstep-card"]';

/** The height a step's card needs next to its target: the card on screen, measured, plus its gap. */
export function cardRoom(doc: Document = document): number {
  const card = doc.querySelector<HTMLElement>(CARD_SELECTOR) ?? doc.querySelector<HTMLElement>(CONTAINER_SELECTOR);
  const height = card?.offsetHeight;
  return height ? height + CARD_GAP : DEFAULT_CARD_ROOM;
}

/** Whether a window this wide shows the card as a bottom sheet. */
export const isSheet = (width: number) => width < SHEET_MAX_WIDTH;

/** A target's box in viewport coordinates. */
export type Box = { top: number; bottom: number; left: number; right: number };
/** The window: its size, how far it is scrolled, the document's full height, and the room the card needs. */
export type View = { width: number; height: number; scrollY: number; docHeight: number; cardRoom: number };

/** Where the card ends up relative to its target: a sheet on a phone, else following the library's own flips
 * (`checkSideCutOff`). */
function placement(side: TourSide, r: Box, v: View): "above" | "below" | "beside" | "sheet" {
  if (isSheet(v.width)) return "sheet";
  const spaceAbove = r.top + v.scrollY;
  const spaceBelow = v.docHeight - (r.bottom + v.scrollY);
  let s: string = side;
  if (s.startsWith("right") && v.width - r.right < SIDE_ROOM) {
    s = r.left >= SIDE_ROOM ? "left" : spaceBelow >= spaceAbove ? "bottom" : "top";
  } else if (s.startsWith("left") && r.left < SIDE_ROOM) {
    s = v.width - r.right >= SIDE_ROOM ? "right" : spaceBelow >= spaceAbove ? "bottom" : "top";
  }
  if (s.includes("top") && spaceAbove < SIDE_ROOM && (spaceBelow >= SIDE_ROOM || spaceBelow > spaceAbove)) s = "bottom";
  else if (s.includes("bottom") && spaceBelow < SIDE_ROOM && (spaceAbove >= SIDE_ROOM || spaceAbove > spaceBelow)) {
    s = "top";
  }
  if (s.startsWith("top")) return "above";
  if (s.startsWith("bottom")) return "below";
  return "beside";
}

/**
 * How far to scroll (in px, down is positive) so a step's target and its card both show below the top bar; 0 when
 * they already do. The tour library scrolls only when a target is off screen, which can leave the card past the
 * bottom of the window or above the top of it.
 */
export function scrollToFit(side: TourSide, r: Box, v: View): number {
  const where = placement(side, r, v);
  // A sheet takes the bottom of the window, as a card below its target does.
  if (where === "below" || where === "sheet") {
    return r.top >= TOP_CLEARANCE && r.bottom + v.cardRoom <= v.height ? 0 : r.top - TOP_CLEARANCE;
  }
  if (where === "above") {
    return r.top - v.cardRoom >= TOP_CLEARANCE && r.bottom <= v.height ? 0 : r.bottom - (v.height - BOTTOM_GAP);
  }
  // Beside the target, the card is centred on it: centre the target in the room under the top bar.
  if (r.top >= TOP_CLEARANCE && r.bottom <= v.height) return 0;
  return (r.top + r.bottom) / 2 - (TOP_CLEARANCE + v.height) / 2;
}

/** Whether a target this tall can show whole, with a card needing `room` above or below it, in a window this tall. */
export const fitsWithCard = (height: number, windowHeight: number, room: number) =>
  height + room <= windowHeight - TOP_CLEARANCE;
