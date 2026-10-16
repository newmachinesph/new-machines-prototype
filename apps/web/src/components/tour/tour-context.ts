"use client";

import { createContext, useContext } from "react";
import type { TourName } from "@/lib/tour/tours";

/** A tour asked for from the menu or the palette, waiting for its page (`href`) to be ready, with the element to
 * give focus back to when it closes. */
export type TourRequest = { name: TourName; href: string; opener: Element | null };

export type TourApi = {
  /** Shows a tour now, whether or not it has been seen. False when nothing started: a tour is already showing, or
   * none of its targets is on the page. Focus returns to `opener` (default: what has focus now) when it closes. */
  start(name: TourName, opener?: Element | null): boolean;
  /** Shows a tour on request (the menu or the palette), on `href` (default: this page). Going elsewhere asks first
   * when there is unsaved work. The request waits in `pending` for that page's `useAutoTour` to start it once the
   * page is ready. */
  replay(name: TourName, options?: { href?: string; opener?: Element | null }): void;
  /** The request still waiting, while the person is on its way to or on its page. */
  pending: TourRequest | null;
  clearPending(): void;
  /** A tour is on screen; other keyboard shortcuts stay out of its way. */
  visible: boolean;
};

/** Outside a TourProvider (unit tests, pages rendered alone) tours do nothing. */
export const TourContext = createContext<TourApi>({
  start: () => false,
  replay: () => {},
  pending: null,
  clearPending: () => {},
  visible: false,
});

export const useTour = (): TourApi => useContext(TourContext);
