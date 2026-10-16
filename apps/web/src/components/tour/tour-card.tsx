"use client";

import { useTranslations } from "next-intl";
import type { CardComponentProps } from "nextstepjs";
import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { Button } from "@/components/ui";

/**
 * One step of a product tour, in the app's own popup style. The tour library places it and draws the spotlight;
 * Escape (skip) and the arrow keys (back, next) are handled there. Focus moves to the step's main button, so Enter
 * goes on, and Tab cycles through the card's buttons. The provider makes the page inert while the card shows and
 * returns focus to it when the tour closes.
 */
export function TourCard({ step, currentStep, totalSteps, nextStep, prevStep, skipTour, arrow }: CardComponentProps) {
  const t = useTranslations("tour.common");
  const titleId = useId();
  const bodyId = useId();
  const primary = useRef<HTMLButtonElement>(null);
  const first = currentStep === 0;
  const last = currentStep === totalSteps - 1;

  useEffect(() => {
    primary.current?.focus({ preventScroll: true });
  }, [currentStep]);

  // Tab and Shift+Tab wrap around the card's buttons rather than leaving it.
  const containFocus = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab") return;
    const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
    if (buttons.length === 0) return;
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.shiftKey ? (at <= 0 ? buttons.length - 1 : at - 1) : at === buttons.length - 1 ? 0 : at + 1;
    e.preventDefault();
    buttons[next].focus();
  };

  return (
    <div
      // A new dialog for each step, so focus moving into it announces the step: the library keeps one card mounted,
      // and Next keeping focus on the same button would announce nothing after step 1.
      key={currentStep}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      onKeyDown={containFocus}
      className="relative w-[min(340px,calc(100vw-2rem))] rounded-[10px] border border-rule bg-paper p-4 text-ink shadow-[0_8px_28px_rgb(17_17_17/0.12)]"
    >
      {/* The library's caret, filled with the card's own colour. */}
      <span className="text-paper" aria-hidden>
        {arrow}
      </span>
      <p className="tnum text-xs text-muted">{t("stepOf", { n: currentStep + 1, total: totalSteps })}</p>
      <h2 id={titleId} className="mt-1 text-base font-semibold">
        {step.title}
      </h2>
      <div id={bodyId} className="mt-1.5 text-sm leading-relaxed text-grey-700">
        {step.content}
      </div>
      <div className="mt-4 flex items-center gap-2">
        {skipTour && !last ? (
          <Button variant="ghost" className="-ml-2 h-8 px-2 text-grey-700" onClick={skipTour}>
            {t("skip")}
          </Button>
        ) : null}
        <div className="ml-auto flex gap-2">
          {first ? null : (
            <Button variant="secondary" className="h-8" onClick={prevStep}>
              {t("back")}
            </Button>
          )}
          <Button ref={primary} className="h-8" onClick={nextStep}>
            {last ? t("done") : t("next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
