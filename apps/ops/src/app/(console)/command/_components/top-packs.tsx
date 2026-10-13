import { Id } from "@/components/ui";
import type { PackCount } from "@/lib/api/gen/types.gen";
import { count } from "@/lib/format";

/** The packs with the most runs in the window the API counts (the last 30 days), most runs first. */
export function TopPacks({ packs }: { packs: PackCount[] }) {
  if (packs.length === 0) {
    return <p className="px-5 py-8 text-center text-sm text-muted">No runs in the last 30 days.</p>;
  }
  return (
    <ol className="divide-y divide-rule">
      {packs.map((p) => (
        <li key={p.slug} className="flex items-baseline justify-between gap-3 px-5 py-2.5 text-sm">
          <span className="min-w-0">
            <span className="block truncate font-medium">{p.name}</span>
            <Id className="block truncate">{p.slug}</Id>
          </span>
          <span className="tnum shrink-0 text-muted">
            {count(p.runs)} run{p.runs === 1 ? "" : "s"}
          </span>
        </li>
      ))}
    </ol>
  );
}
