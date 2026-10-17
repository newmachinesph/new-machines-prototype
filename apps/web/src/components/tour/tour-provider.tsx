"use client";

import { MotionGlobalConfig, useReducedMotion } from "motion/react";
import { useTranslations } from "next-intl";
import { NextStep, NextStepProvider, useNextStep } from "nextstepjs";
import { useNextAdapter } from "nextstepjs/adapters/next";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cardRoom, scrollToFit, TOP_CLEARANCE } from "@/lib/tour/fit";
import { markSeen } from "@/lib/tour/seen";
import { resolveSteps, TOURS, type ResolvedStep, type TourName } from "@/lib/tour/tours";
import { useConfirmLeave } from "@/lib/use-leave-guard";
import { TourCard } from "./tour-card";
import { TourContext, useTour, type TourApi, type TourRequest } from "./tour-context";

export { useTour };

// The page dims as under the app's own dialogs: ink at a quarter.
const SHADE_RGB = "17, 17, 17";
const SHADE_OPACITY = "0.25";
const CARD_MOTION = { ease: "easeOut", duration: 0.3 } as const;
// NextStep renders the app inside this element; the card and overlay are portalled outside it.
const SITE_SELECTOR = '[data-name="nextstep-site"]';
/** The shell's main content (focusable with tabIndex -1), where focus lands after a tour nothing opened. */
const mainContent = () => document.getElementById("main");
/** How long a replay waits for its page to be ready before it is dropped. */
const PENDING_MS = 15_000;

const isTourName = (name: string | null): name is TourName => name !== null && Object.hasOwn(TOURS, name);

type ActiveTour = { name: TourName; steps: ResolvedStep[] };

/**
 * While a tour shows, the page behind it is inert, so neither Tab nor a screen reader leaves the card. When it
 * closes, focus goes back to whatever had it when the tour started, or to the page's main content when nothing did
 * (a tour that started by itself) or that element has gone.
 */
function useTourModality(visible: boolean, opener: { current: Element | null }) {
  useEffect(() => {
    if (!visible) return;
    const site = document.querySelector(SITE_SELECTOR);
    site?.setAttribute("inert", "");
    return () => {
      site?.removeAttribute("inert");
      const el = opener.current;
      opener.current = null;
      const back = el instanceof HTMLElement && el !== document.body && el.isConnected ? el : mainContent();
      // After inert is lifted, or the focus call would be ignored.
      back?.focus({ preventScroll: true });
    };
  }, [visible, opener]);
}

/** In the sidebar or another pinned container, where scrolling the page does not move it. */
function isPinned(el: Element): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) {
    const { position } = getComputedStyle(node);
    if (position === "fixed" || position === "sticky") return true;
  }
  return false;
}

/**
 * Brings each step's target and its card into view together, under the top bar. The library scrolls only to a
 * target that is off screen, so a target near the bottom of the window could leave its card below it. Runs after the
 * library's own scroll for the step, and replaces it.
 */
function useFitStep(step: ResolvedStep | undefined, reduceMotion: boolean | null) {
  useEffect(() => {
    if (!step?.selector || !step.side) return;
    const el = document.querySelector(step.selector);
    if (!el || isPinned(el)) return;
    const view = {
      width: window.innerWidth,
      height: window.innerHeight,
      scrollY: window.scrollY,
      docHeight: document.documentElement.scrollHeight,
      cardRoom: cardRoom(),
    };
    const delta = scrollToFit(step.side, el.getBoundingClientRect(), view);
    if (Math.abs(delta) >= 1) window.scrollBy({ top: delta, behavior: reduceMotion ? "instant" : "smooth" });
  }, [step, reduceMotion]);
}

/** A replay request, and whether the person has reached its page yet. */
type Waiting = { request: TourRequest; arrived: boolean };

/**
 * Replay requests wait for their page to be ready. One is dropped when the person leaves its page without the tour
 * starting, or after a while, so it never pops up later out of nowhere. Leaving for another page asks first when a
 * page holds unsaved work.
 */
function usePendingReplay() {
  const router = useRouter();
  const pathname = usePathname();
  const mayLeave = useConfirmLeave();
  const [waiting, setWaiting] = useState<Waiting | null>(null);

  // Adjusted while rendering, as React recommends for state that follows a prop (here, the path).
  if (waiting) {
    const here = pathname === waiting.request.href;
    if (here && !waiting.arrived) setWaiting({ ...waiting, arrived: true });
    else if (!here && waiting.arrived) setWaiting(null);
  }

  const request = waiting?.request;
  useEffect(() => {
    if (!request) return;
    const timer = setTimeout(() => setWaiting(null), PENDING_MS);
    return () => clearTimeout(timer);
  }, [request]);

  const replay = useCallback<TourApi["replay"]>(
    (name, { href = pathname, opener = document.activeElement } = {}) => {
      const away = href !== pathname;
      if (away && !mayLeave()) return;
      setWaiting({ request: { name, href, opener }, arrived: !away });
      if (away) router.push(href);
    },
    [pathname, router, mayLeave],
  );
  const clearPending = useCallback(() => setWaiting(null), []);
  // Only on its own page: on the way there, the page being left must not start it.
  const pending = request && pathname === request.href ? request : null;
  return { replay, pending, clearPending };
}

function TourHost({ children }: { children: ReactNode }) {
  const t = useTranslations("tour");
  const { startNextStep, isNextStepVisible, currentStep } = useNextStep();
  const reduceMotion = useReducedMotion();
  const [active, setActive] = useState<ActiveTour | null>(null);
  const opener = useRef<Element | null>(null);

  useTourModality(isNextStepVisible, opener);
  useFitStep(isNextStepVisible ? active?.steps[currentStep] : undefined, reduceMotion);

  // Under reduced motion the spotlight, overlay and card jump straight to place. MotionConfig's reducedMotion only
  // stops transform animations, and the spotlight animates SVG attributes with its own transition. The tour is the
  // only user of motion in the app.
  useEffect(() => {
    MotionGlobalConfig.skipAnimations = Boolean(reduceMotion);
  }, [reduceMotion]);

  // The steps are fitted to the page when the tour starts, so a missing target is skipped rather than pointed at.
  // A tour already on screen is left alone.
  const start = useCallback(
    (name: TourName, from: Element | null = document.activeElement) => {
      if (isNextStepVisible) return false;
      const steps = resolveSteps(TOURS[name]);
      if (steps.length === 0) return false;
      opener.current = from;
      setActive({ name, steps });
      startNextStep(name);
      return true;
    },
    [isNextStepVisible, startNextStep],
  );

  const { replay, pending, clearPending } = usePendingReplay();
  const api = useMemo<TourApi>(
    () => ({ start, replay, pending, clearPending, visible: isNextStepVisible }),
    [start, replay, pending, clearPending, isNextStepVisible],
  );

  const tours = useMemo(() => {
    if (!active) return [];
    // Keys are built from TOURS; tours.test.ts checks every one has its copy in both languages.
    type Key = Parameters<typeof t>[0];
    const copy = (key: string, part: "title" | "body") => t(`${active.name}.${key}.${part}` as Key);
    return [
      {
        tour: active.name,
        steps: active.steps.map((s) => ({
          title: copy(s.key, "title"),
          content: copy(s.key, "body"),
          selector: s.selector,
          side: s.side,
          // The tour explains; it does not navigate. Clicks on the highlighted element wait until it closes.
          disableInteraction: true,
          // A step with no target (centred, or a sheet on a phone) gets no spotlight: padding alone would draw a
          // dot in the middle of the window.
          pointerPadding: s.selector ? 8 : 0,
          pointerRadius: s.selector ? 10 : 0,
          // A target scrolled into view clears the sticky top bar.
          scrollOffset: TOP_CLEARANCE,
        })),
      },
    ];
  }, [active, t]);

  const recordSeen = useCallback((name: string | null) => {
    if (isTourName(name)) markSeen(name);
  }, []);

  return (
    <TourContext value={api}>
      <NextStep
        steps={tours}
        cardComponent={TourCard}
        navigationAdapter={useNextAdapter}
        onComplete={recordSeen}
        onSkip={(_step, name) => recordSeen(name)}
        shadowRgb={SHADE_RGB}
        shadowOpacity={SHADE_OPACITY}
        cardTransition={CARD_MOTION}
        disableConsoleLogs
        // Scroll only to bring an off-screen target into view, never to the top or to every target.
        scrollToTop={false}
        noInViewScroll
      >
        {children}
      </NextStep>
    </TourContext>
  );
}

/** Product tours for the whole app: `useTour().start(name)` shows one, `useAutoTour` starts one on first visit. */
export function TourProvider({ children }: { children: ReactNode }) {
  return (
    <NextStepProvider>
      <TourHost>{children}</TourHost>
    </NextStepProvider>
  );
}
