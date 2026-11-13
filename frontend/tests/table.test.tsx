import { render, screen } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";
import { describe, expect, it, vi } from "vitest";
import { GlassTable } from "@/components/ui/table";

interface Row { roll: string; name: string }
const cols: ColumnDef<Row, unknown>[] = [{ accessorKey: "roll", header: "Roll" }, { accessorKey: "name", header: "Name" }];
const data: Row[] = [{ roll: "R1", name: "Asha" }, { roll: "R2", name: "Bimal" }, { roll: "R3", name: "Chitra" }];

describe("GlassTable", () => {
  it("shows every row without a filter", () => {
    render(<GlassTable data={data} columns={cols} />);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("filters rows by the global filter, case-insensitively", () => {
    render(<GlassTable data={data} columns={cols} globalFilter="bim" />);
    expect(screen.getByText("Bimal")).toBeInTheDocument();
    expect(screen.queryByText("Asha")).not.toBeInTheDocument();
  });

  it("shows the empty state when nothing matches", () => {
    render(<GlassTable data={data} columns={cols} globalFilter="zzz" emptyTitle="No matches" />);
    expect(screen.getByText("No matches")).toBeInTheDocument();
  });

  it("shows an error message instead of the empty state", () => {
    render(<GlassTable data={[]} columns={cols} error="Request failed (500)" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Request failed (500)");
    expect(screen.queryByText("Nothing here yet")).not.toBeInTheDocument();
  });

  it("drives server pagination", () => {
    const onPage = vi.fn();
    render(<GlassTable data={data} columns={cols} pagination={{ page: 2, pageSize: 3, total: 9, onPage }} />);
    expect(screen.getByText("Page 2 / 3")).toBeInTheDocument();
    screen.getByLabelText("Next page").click();
    expect(onPage).toHaveBeenCalledWith(3);
    screen.getByLabelText("Previous page").click();
    expect(onPage).toHaveBeenCalledWith(1);
  });
});
