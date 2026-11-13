"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import type { AttendanceRow, Page } from "@/lib/types";
import { toQuery } from "@/lib/utils";
import { attendanceColumns } from "@/components/features/columns";
import { PageHeader } from "@/components/features/shared";
import { GlassCard } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";

const PAGE_SIZE = 25;
const columns = attendanceColumns.slice(0, 4);

export default function StudentAttendance() {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["me-attendance", start, end, page], queryFn: () => api<Page<AttendanceRow>>(`/me/attendance${toQuery({ start_date: start, end_date: end, page, page_size: PAGE_SIZE })}`) });
  return (
    <div className="space-y-5">
      <PageHeader title="My attendance" description="Only your own records are shown" />
      <GlassCard className="flex flex-wrap items-end gap-3">
        <div><label className="label" htmlFor="a-start">From</label><input id="a-start" type="date" className="field" value={start} onChange={(e) => { setStart(e.target.value); setPage(1); }} /></div>
        <div><label className="label" htmlFor="a-end">To</label><input id="a-end" type="date" className="field" value={end} onChange={(e) => { setEnd(e.target.value); setPage(1); }} /></div>
      </GlassCard>
      <GlassTable data={q.data?.items ?? []} columns={columns} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null}
        pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: setPage }} emptyTitle="No attendance in this range" caption="My attendance" />
    </div>
  );
}
