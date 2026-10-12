"use client";

import { type CSSProperties, type ReactNode, useEffect, useRef } from "react";

// Stages that come into view together (side by side on wide screens) keep their offsets and play
// left to right; a stage scrolled to later plays at once.
const TOGETHER_MS = 300;
let firstPlayAt: number | null = null;

// Plays a stage's rail and lines once any of it scrolls into view. The hide rules in globals.css
// apply only with scripting on and motion allowed, so no-JS, reduced motion and print show it complete.
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
    if (!el) return;
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
    return () => io.disconnect();
  }, []);

  return (
    <li ref={ref} data-armed="" className={className} style={{ "--s": `${offset}s` } as CSSProperties}>
      {children}
    </li>
  );
}
