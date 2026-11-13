"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { StatusBadge } from "@/components/ui/glass";
import type { AttendanceRow } from "@/lib/types";
import { fmtPct } from "@/lib/utils";

export const attendanceColumns: ColumnDef<AttendanceRow, unknown>[] = [
  { accessorKey: "timestamp", header: "Time" },
  { accessorKey: "roll_number", header: "Roll no." },
  { accessorKey: "name", header: "Name" },
  { accessorKey: "direction", header: "Direction" },
  { accessorKey: "similarity", header: "Similarity", cell: ({ getValue }) => fmtPct(getValue() as number, 1) },
  { accessorKey: "camera_label", header: "Camera" },
  {
    accessorKey: "pad_state", header: "Liveness",
    cell: ({ row }) => row.original.pad_state
      ? <StatusBadge color={row.original.pad_state === "LIVE" ? "#22c55e" : "#9ca3af"} label={`${row.original.pad_state}${row.original.pad_score !== null ? ` ${fmtPct(row.original.pad_score)}` : ""}`} />
      : <span className="text-xs text-muted">not checked</span>,
  },
];
