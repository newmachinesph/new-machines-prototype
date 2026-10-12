import { cn } from "@/lib/cn";
import { lockup } from "./lockup.data";
import type { LogoProps } from "./Mark";

export function Lockup({ className, title = "New Machines", trim = false }: LogoProps & { trim?: boolean }) {
  return (
    <svg
      viewBox={trim ? "103.57 81 1088.86 297" : lockup.viewBox}
      preserveAspectRatio={trim ? "xMinYMin meet" : undefined}
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      className={cn("block h-16 w-auto", className)}
      dangerouslySetInnerHTML={{ __html: lockup.body }}
    />
  );
}
