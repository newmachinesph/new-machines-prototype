"use client";

import { type CSSProperties, type ReactNode, useEffect, useRef } from "react";

// Stages that come into view together (side by side on wide screens) keep their offsets and play
// left to right; a stage scrolled to later plays at once.
const TOGETHER_MS = 300;
let firstPlayAt: number | null = null;

// Only a stage wholly below the fold at hydration is armed. One partly on screen stays visible: the observer's
// -15% bottom margin would not count it as in view, so arming it would hide it until the next scroll.

// Plays a stage's rail and lines once it scrolls into view. The stage renders complete and is hidden
// ("armed") only on the client, once it is known that motion is allowed, an observer exists and the stage
// is still below the fold, so no-JS, reduced motion, print and a stage already on screen all show it whole.
export function StageReveal({
  offset,
  className,
  children,
}: {
  offset: number;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLLIElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !canReveal(el)) return;
    el.dataset.armed = "";
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        const now = performance.now();
        firstPlayAt ??= now;
        if (now - firstPlayAt > TOGETHER_MS) el.style.setProperty("--s", "0s");
        el.dataset.play = "";
        io.disconnect();
      },
      { rootMargin: "0px 0px -15% 0px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      delete el.dataset.armed;
    };
  }, []);

  return (
    <li ref={ref} className={className} style={{ "--s": `${offset}s` } as CSSProperties}>
      {children}
    </li>
  );
}

function canReveal(el: HTMLElement): boolean {
  if (!("IntersectionObserver" in window) || typeof window.matchMedia !== "function") return false;
  if (!window.matchMedia("(prefers-reduced-motion: no-preference)").matches) return false;
  return el.getBoundingClientRect().top > window.innerHeight;
}
