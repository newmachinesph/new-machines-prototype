import { money, date } from "@/lib/format";
import type { UsagePoint } from "@/lib/api/gen/types.gen";

const W = 640;
const H = 160;
const PAD = { t: 8, r: 4, b: 22, l: 4 };

/** Daily AI spend as inline SVG bars. The title and the hidden table carry the data for assistive tech. */
export function UsageChart({ points }: { points: UsagePoint[] }) {
  if (points.length === 0) return <p className="px-5 py-8 text-sm text-muted">No usage in the last 14 days.</p>;
  const max = Math.max(...points.map((p) => p.amountMinor), 1);
  const slot = (W - PAD.l - PAD.r) / points.length;
  const bar = slot * 0.62;
  const plotH = H - PAD.t - PAD.b;
  const total = points.reduce((s, p) => s + p.amountMinor, 0);
  const label = `Daily spend over the last ${points.length} days, ${money(total)} in total, peak ${money(max)}`;
  return (
    <div className="px-5 py-4">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-40 w-full">
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="stroke-rule" />
        {points.map((p, i) => {
          const h = Math.max(p.amountMinor > 0 ? 2 : 0, (p.amountMinor / max) * plotH);
          const x = PAD.l + i * slot + (slot - bar) / 2;
          return (
            <g key={p.day}>
              <rect x={x} y={H - PAD.b - h} width={bar} height={h} rx={2} className="fill-ink">
                <title>{`${date(p.day)}: ${money(p.amountMinor)}`}</title>
              </rect>
              {i % 2 === 0 || points.length < 8 ? (
                <text x={x + bar / 2} y={H - 6} textAnchor="middle" className="fill-muted text-[10px]">
                  {date(p.day)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>Daily spend</caption>
        <thead>
          <tr>
            <th>Day</th>
            <th>Spend</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.day}>
              <td>{date(p.day)}</td>
              <td>{money(p.amountMinor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
