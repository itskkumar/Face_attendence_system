"use client";
import { flexRender, getCoreRowModel, getFilteredRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Inbox } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { EmptyState, GlassButton, Skeleton } from "./glass";

export interface ServerPagination { page: number; pageSize: number; total: number; onPage: (p: number) => void }

export function GlassTable<T>({ data, columns, loading, error, globalFilter, pagination, emptyTitle = "Nothing here yet", emptyDescription, emptyAction, caption }: {
  data: T[]; columns: ColumnDef<T, unknown>[]; loading?: boolean; error?: string | null; globalFilter?: string;
  pagination?: ServerPagination; emptyTitle?: string; emptyDescription?: string; emptyAction?: ReactNode; caption?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data, columns, state: { sorting, globalFilter: globalFilter ?? "" }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: "includesString",
  });
  const rows = table.getRowModel().rows;
  const pages = pagination ? Math.max(1, Math.ceil(pagination.total / pagination.pageSize)) : 1;

  return (
    <div className="glass overflow-hidden rounded-xl2">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="text-xs uppercase tracking-wide text-muted">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-[var(--glass-border)]">
                {hg.headers.map((h) => {
                  const sortable = h.column.getCanSort();
                  const dir = h.column.getIsSorted();
                  return (
                    <th key={h.id} scope="col" aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"} className="px-4 py-3 font-medium">
                      {h.isPlaceholder ? null : sortable ? (
                        <button type="button" onClick={h.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 hover:text-fg">
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {dir === "asc" ? <ArrowUp className="h-3 w-3" /> : dir === "desc" ? <ArrowDown className="h-3 w-3" /> : null}
                        </button>
                      ) : flexRender(h.column.columnDef.header, h.getContext())}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading && Array.from({ length: 5 }).map((_, i) => (
              <tr key={`sk${i}`}><td colSpan={columns.length} className="px-4 py-2"><Skeleton className="h-6 w-full" /></td></tr>
            ))}
            {!loading && rows.map((r) => (
              <tr key={r.id} className="border-b border-[var(--glass-border)]/60 transition hover:bg-[var(--glass-strong)]">
                {r.getVisibleCells().map((c) => <td key={c.id} className="px-4 py-2.5 align-middle">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p role="alert" className="px-4 py-6 text-center text-sm text-danger">{error}</p>}
      {!loading && !error && rows.length === 0 && <EmptyState icon={<Inbox className="h-5 w-5" />} title={emptyTitle} description={emptyDescription} action={emptyAction} />}
      {pagination && (
        <div className="flex items-center justify-between gap-2 border-t border-[var(--glass-border)] px-4 py-2.5 text-xs text-muted">
          <span>{pagination.total.toLocaleString()} total</span>
          <div className="flex items-center gap-2">
            <GlassButton variant="ghost" className="px-2 py-1" aria-label="Previous page" disabled={pagination.page <= 1} onClick={() => pagination.onPage(pagination.page - 1)}><ChevronLeft className="h-4 w-4" /></GlassButton>
            <span className={cn("tabular-nums")}>Page {pagination.page} / {pages}</span>
            <GlassButton variant="ghost" className="px-2 py-1" aria-label="Next page" disabled={pagination.page >= pages} onClick={() => pagination.onPage(pagination.page + 1)}><ChevronRight className="h-4 w-4" /></GlassButton>
          </div>
        </div>
      )}
    </div>
  );
}
