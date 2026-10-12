import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type Column, DataTable } from "./data-table";

type Row = { id: string; name: string; runs: number };
const COLUMNS: Column<Row>[] = [
  { key: "name", header: "Tenant", cell: (r) => r.name },
  { key: "runs", header: "Runs (30d)", cell: (r) => r.runs, numeric: true },
];
const ROWS: Row[] = [
  { id: "org_hp01", name: "Harbor & Pine Supply Co.", runs: 412 },
  { id: "org_ks02", name: "Kisaragi Ceramics", runs: 88 },
];

describe("DataTable", () => {
  it("shows the empty state in place of rows, keeping the headers", () => {
    render(
      <DataTable
        label="Tenants"
        columns={COLUMNS}
        rows={[]}
        rowKey={(r) => r.id}
        empty="No tenants match these filters."
      />,
    );
    const table = screen.getByRole("table", { name: "Tenants" });
    expect(within(table).getByRole("columnheader", { name: "Tenant" })).toBeInTheDocument();
    const cell = within(table).getByRole("cell", { name: "No tenants match these filters." });
    expect(cell).toHaveAttribute("colspan", "2");
  });

  it("links each row from its first cell", () => {
    render(
      <DataTable
        label="Tenants"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        rowHref={(r) => `/tenants/${r.id}`}
      />,
    );
    expect(screen.getByRole("link", { name: "Harbor & Pine Supply Co." })).toHaveAttribute("href", "/tenants/org_hp01");
    expect(screen.getByRole("link", { name: "Kisaragi Ceramics" })).toHaveAttribute("href", "/tenants/org_ks02");
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("renders no links without rowHref", () => {
    render(<DataTable label="Tenants" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByRole("cell", { name: "Harbor & Pine Supply Co." })).toBeInTheDocument();
  });

  it("right-aligns numeric columns with tabular figures", () => {
    render(<DataTable label="Tenants" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("columnheader", { name: "Runs (30d)" })).toHaveClass("text-right");
    expect(screen.getByRole("cell", { name: "412" })).toHaveClass("text-right", "tnum");
  });

  it("names its scroll region so keyboard users can reach it", () => {
    render(<DataTable label="Tenants" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />);
    expect(screen.getByRole("region", { name: "Tenants" })).toHaveAttribute("tabindex", "0");
  });
});
