import { DataTable, type Column } from "@/components/data-table";
import type { AuditEntry } from "@/lib/api/gen/types.gen";
import { ago, dateTime } from "@/lib/format";

const columns: Column<AuditEntry>[] = [
  {
    key: "at",
    header: "When",
    cell: (e) => (
      <time dateTime={e.at} title={dateTime(e.at)} className="tnum whitespace-nowrap text-muted">
        {ago(e.at)}
      </time>
    ),
  },
  {
    key: "summary",
    header: "Change",
    cell: (e) => (
      <div className="min-w-0">
        <div className="font-medium">{e.summary}</div>
        <div className="text-[13px] text-muted">{e.reason}</div>
        <div className="mt-0.5 text-xs text-muted">
          {e.actorEmail} ({e.actorRole})
        </div>
      </div>
    ),
  },
];

/** Five rows fit beside the chart without an inner scroll; the full log is one click away. */
const FEED_ROWS = 5;

export function AuditFeed({ entries }: { entries: AuditEntry[] }) {
  return (
    <DataTable
      label="Recent operator actions"
      columns={columns}
      rows={entries.slice(0, FEED_ROWS)}
      rowKey={(e) => e.id}
      empty="No operator actions yet. Changes made in the console are recorded here."
    />
  );
}
