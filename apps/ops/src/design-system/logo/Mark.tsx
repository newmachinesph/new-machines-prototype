import { cn } from "@/lib/cn";
import { mark } from "./mark.data";

export type LogoProps = { className?: string; title?: string; trim?: boolean };

// The body is plain polygons (no ids, defs or clip paths), so any number of
// instances can share a page.
export function Mark({ className, title = "New Machines", trim = false }: LogoProps) {
  return (
    <svg
      viewBox={trim ? "103.57 81 1088.86 198" : mark.viewBox}
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      className={cn("block h-8 w-auto", className)}
      dangerouslySetInnerHTML={{ __html: mark.body }}
    />
  );
}
