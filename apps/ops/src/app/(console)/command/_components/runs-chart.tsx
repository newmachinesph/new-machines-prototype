import { SampleTag, SimTag } from "@/components/ui";
import type { HourPoint } from "@/lib/api/gen/types.gen";
import { count } from "@/lib/format";
import { maxHourTotal } from "./logic";

const W = 480;
const H = 150;
const PAD = { top: 6, right: 4, bottom: 20, left: 4 };
const SERIES = [
  { key: "completed", label: "Completed", fill: "var(--color-ink)" },
  { key: "waiting", label: "Waiting", fill: "var(--color-human)" },
  { key: "failed", label: "Failed", fill: "var(--color-blocked)" },
] as const;

const MIN_SEGMENT = 2;

const hh = (hour: number) => String(hour).padStart(2, "0");

export type ChartTag = "simulated" | "sample" | null;

const TAG_TEXT: Record<Exclude<ChartTag, null>, string> = { simulated: "Simulated", sample: "Sample" };

/**
 * Runs per hour (UTC) today as stacked inline-SVG bars. The visually hidden table is the accessible version.
 * `tag` says where the series comes from: simulated (the demo), sample (a live fixture) or none (live data).
 */
export function RunsChart({ points, tag = "simulated" }: { points: HourPoint[]; tag?: ChartTag }) {
  const tagText = tag ? ` ${TAG_TEXT[tag]}.` : "";
  const max = maxHourTotal(points);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const slot = innerW / Math.max(1, points.length);
  const bar = Math.max(2, slot - 3);
  const total = points.reduce((n, p) => n + p.completed + p.failed + p.waiting, 0);

  return (
    <div className="px-5 py-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {SERIES.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-[2px]" style={{ background: s.fill }} />
              {s.label}
            </li>
          ))}
        </ul>
        {tag === "simulated" ? <SimTag /> : tag === "sample" ? <SampleTag /> : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Runs by hour today, UTC, ${count(total)} in total. Stacked bars of completed, waiting and failed runs.${tag ? ` ${TAG_TEXT[tag]} data.` : ""}`}
        className="block h-auto w-full"
      >
        <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} stroke="var(--color-rule)" />
        {points.map((p, i) => {
          const x = PAD.left + i * slot + (slot - bar) / 2;
          let y = H - PAD.bottom;
          return (
            <g key={p.hour}>
              <title>{`${hh(p.hour)}:00 UTC: ${p.completed} completed, ${p.waiting} waiting, ${p.failed} failed`}</title>
              {SERIES.map((s) => {
                if (p[s.key] <= 0) return null;
                const h = Math.max(MIN_SEGMENT, (p[s.key] / max) * innerH);
                y -= h;
                return <rect key={s.key} x={x} y={y} width={bar} height={h} fill={s.fill} />;
              })}
              {p.hour % 6 === 0 ? (
                <text x={x + bar / 2} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--color-muted)">
                  {hh(p.hour)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>{`Runs by hour today, UTC.${tagText}`}</caption>
        <thead>
          <tr>
            <th scope="col">Hour</th>
            <th scope="col">Completed</th>
            <th scope="col">Waiting</th>
            <th scope="col">Failed</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.hour}>
              <th scope="row">{hh(p.hour)}:00</th>
              <td>{p.completed}</td>
              <td>{p.waiting}</td>
              <td>{p.failed}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
