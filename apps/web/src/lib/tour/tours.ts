import type { Step } from "nextstepjs";
import { cardRoom, fitsWithCard } from "./fit";

/** The product tours. Their copy lives in messages under `tour.<name>.<key>.title|body`. */
export type TourName = "welcome" | "studio" | "run";

export type TourSide = NonNullable<Step["side"]>;

export type TourStepDef = {
  key: string;
  /** Always `[data-tour="…"]`, so styling ids and classes stay free to change. */
  selector: string;
  side?: TourSide;
  /** For targets that can be on the page but hidden, such as the sidebar below lg where the nav is in a drawer:
   * the step then shows as a centred card with no pointer, instead of pointing at nothing. */
  centerWhenHidden?: boolean;
  /** A smaller part of a tall target, such as a panel's title row, to point at when the whole target and the card
   * cannot both show in the window. */
  head?: string;
};

const target = (value: string) => `[data-tour="${value}"]`;
/** The title row of a panel (`Section`, `CollapsibleSection` and the run's steps panel all start with one). */
const titleRow = (value: string) => `${target(value)} > :first-child`;

export const TOURS: Record<TourName, TourStepDef[]> = {
  welcome: [
    { key: "ask", selector: target("ask-box"), side: "bottom" },
    { key: "marketplace", selector: target("nav-marketplace"), side: "right", centerWhenHidden: true },
    { key: "runs", selector: target("nav-runs"), side: "right", centerWhenHidden: true },
    { key: "approvals", selector: target("nav-approvals"), side: "right", centerWhenHidden: true },
    { key: "usage", selector: target("nav-usage"), side: "right", centerWhenHidden: true },
    // The account menu is at the bottom of the sidebar: the card sits to its right, bottoms aligned.
    { key: "help", selector: target("account-menu"), side: "right-bottom", centerWhenHidden: true },
  ],
  // The Studio exists in a live workspace only, and its home shows all four of these.
  studio: [
    { key: "intro", selector: target("studio-intro"), side: "bottom" },
    { key: "agents", selector: target("studio-agents"), side: "bottom" },
    { key: "packs", selector: target("studio-packs"), side: "bottom" },
    { key: "publisher", selector: target("studio-publisher"), side: "top" },
  ],
  // A run asks for attention only while something waits on the buyer, and only a real run has a receipt; those
  // steps are skipped when their target is not on the page.
  run: [
    { key: "steps", selector: target("run-steps"), side: "bottom", head: titleRow("run-steps") },
    { key: "step", selector: target("run-step"), side: "left", head: titleRow("run-step") },
    { key: "attention", selector: target("run-attention"), side: "bottom" },
    { key: "timeline", selector: target("run-timeline"), side: "bottom", head: titleRow("run-timeline") },
    { key: "cost", selector: target("run-cost"), side: "left", head: titleRow("run-cost") },
    { key: "receipt", selector: target("run-receipt"), side: "left", head: titleRow("run-receipt") },
  ],
};

/** Where a tour can be replayed: its tour, and the page it runs on. */
export type TourArea = { name: TourName; href: string };

/** The tour for the area a page belongs to: a run and its evidence replay the run tour on the run page; the rest of
 * the workspace replays the welcome tour on the overview, and the Studio its tour on the Studio home. The reviewer
 * portal has none. */
export function tourFor(path: string): TourArea | null {
  const run = /^\/app\/runs\/([^/]+)(?:\/evidence)?$/.exec(path);
  if (run && run[1] !== "new") return { name: "run", href: `/app/runs/${run[1]}` };
  if (path === "/app" || path.startsWith("/app/")) return { name: "welcome", href: "/app" };
  if (path === "/studio" || path.startsWith("/studio/")) return { name: "studio", href: "/studio" };
  return null;
}

/** A step as it will show now: pointing at its target, or centred when `selector` is undefined. */
export type ResolvedStep = { key: string; selector: string | undefined; side: TourSide | undefined };

/** Laid out on screen. An element under `display: none` (or detached) has no client rects. */
const isShown = (el: Element) => el.getClientRects().length > 0;

/**
 * Fits a tour to the page as it is: a step whose target is missing is dropped, and a hidden target either
 * centres its step or drops it. A target too tall to show whole beside the card is pointed at by its `head`. The
 * tour library itself points at the first element matching a selector, so visibility is judged on that same element.
 */
export function resolveSteps(defs: TourStepDef[], doc: Document = document): ResolvedStep[] {
  const windowHeight = doc.defaultView?.innerHeight ?? 0;
  return defs.flatMap(({ key, selector, side, centerWhenHidden, head }): ResolvedStep[] => {
    const el = doc.querySelector(selector);
    if (!el) return [];
    if (!isShown(el)) return centerWhenHidden ? [{ key, selector: undefined, side: undefined }] : [];
    const tall = !fitsWithCard(el.getBoundingClientRect().height, windowHeight, cardRoom(doc));
    const headEl = head && tall ? doc.querySelector(head) : null;
    return [{ key, selector: headEl && isShown(headEl) ? head : selector, side }];
  });
}

/** `NEXT_PUBLIC_TOURS=off` (the e2e build) stops tours starting by themselves; replay still works. Read where it is
 * used, so Next inlines it and tests can stub it. */
export const autoStartEnabled = () => process.env.NEXT_PUBLIC_TOURS !== "off";
