import { cn } from "@/lib/cn";

/** A quiet placeholder block. Pulses only when motion is allowed. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("rounded-md bg-grey-100 motion-safe:animate-pulse", className)} />;
}
