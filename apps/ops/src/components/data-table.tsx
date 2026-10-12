import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Column<T> = {
  /** Stable id for the column, also its React key. */
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-aligns the header and cells and uses tabular figures. Use for counts, money and rates. */
  numeric?: boolean;
  /** Extra classes on this column's header and cells, e.g. a width or "hidden md:table-cell". */
  className?: string;
};

export type DataTableProps<T> = {
  /** Names the table for assistive tech (a hidden caption) and its scroll region. */
  label: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /**
   * Makes each row open a page: the first column's content becomes the link and the whole row is clickable.
   * Links and buttons in other cells still work on their own.
   */
  rowHref?: (row: T) => string;
  /** Shown in place of the rows when there are none. Say why and what to do: "No tenants match these filters." */
  empty?: ReactNode;
  /** Tailwind max-height for the scroll region; the header sticks while rows scroll. */
  maxHeight?: string;
  className?: string;
};

/**
 * A dense, accessible table: sticky header, optional row links, an empty state, and numeric columns
 * right-aligned with tabular figures. Wide tables scroll inside their own region, never the page.
 * Place it inside a `Section` (a `.panel`) for the card look.
 */
export function DataTable<T>({
  label,
  columns,
  rows,
  rowKey,
  rowHref,
  empty = "Nothing to show yet.",
  maxHeight = "max-h-[70vh]",
  className,
}: DataTableProps<T>) {
  return (
    // A scroll container needs to be focusable so keyboard users can scroll it.
    <div role="region" aria-label={label} tabIndex={0} className={cn("overflow-auto", maxHeight, className)}>
      <table className="w-full border-separate border-spacing-0 text-sm">
        <caption className="sr-only">{label}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  "sticky top-0 z-[2] border-b border-rule bg-paper px-4 py-2 text-left text-xs font-medium whitespace-nowrap text-muted",
                  c.numeric && "text-right",
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-sm text-muted">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const href = rowHref?.(row);
              return (
                <tr key={rowKey(row)} className={cn("group", href && "relative hover:bg-grey-50")}>
                  {columns.map((c, i) => (
                    <td
                      key={c.key}
                      className={cn(
                        "border-b border-rule px-4 py-2.5 align-middle group-last:border-b-0",
                        c.numeric && "tnum text-right whitespace-nowrap",
                        // Interactive content in other cells sits above the row's stretched link.
                        href && i > 0 && "[&_a]:relative [&_a]:z-[1] [&_button]:relative [&_button]:z-[1]",
                        c.className,
                      )}
                    >
                      {href && i === 0 ? (
                        <Link
                          href={href}
                          className="font-medium text-ink outline-none after:absolute after:inset-0 hover:underline focus-visible:underline focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-machine"
                        >
                          {c.cell(row)}
                        </Link>
                      ) : (
                        c.cell(row)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
