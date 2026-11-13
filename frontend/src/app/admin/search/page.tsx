"use client";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type ChangeEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import type { AttendanceRow, Page } from "@/lib/types";
import { toQuery } from "@/lib/utils";
import { attendanceColumns } from "@/components/features/columns";
import { PageHeader } from "@/components/features/shared";
import { GlassCard } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";

const PAGE_SIZE = 25;
type Filters = { start_date: string; end_date: string; roll_number: string; name: string; camera_label: string; direction: string };

function SearchView() {
  const sp = useSearchParams();
  const [draft, setDraft] = useState<Filters>({ start_date: "", end_date: "", roll_number: "", name: sp.get("name") ?? "", camera_label: "", direction: "" });
  const [applied, setApplied] = useState<Filters>(draft);
  const [page, setPage] = useState(1);
  const cams = useQuery({ queryKey: ["att-cameras"], queryFn: () => api<string[]>("/attendance/cameras") });
  const q = useQuery({ queryKey: ["attendance", applied, page], queryFn: () => api<Page<AttendanceRow>>(`/attendance${toQuery({ ...applied, page, page_size: PAGE_SIZE })}`) });
  const set = (k: keyof Filters) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  return (
    <div className="space-y-5">
      <PageHeader title="Search attendance" description="Filter the attendance log; results are paginated on the server"
        actions={<a className="glass inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm hover:brightness-110" href={`/api/attendance/export.csv${toQuery(applied)}`}><Download className="h-4 w-4" />Export CSV</a>} />
      <GlassCard>
        <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6" onSubmit={(e) => { e.preventDefault(); setPage(1); setApplied(draft); }}>
          <div><label className="label" htmlFor="f-start">From</label><input id="f-start" type="date" className="field" value={draft.start_date} onChange={set("start_date")} /></div>
          <div><label className="label" htmlFor="f-end">To</label><input id="f-end" type="date" className="field" value={draft.end_date} onChange={set("end_date")} /></div>
          <div><label className="label" htmlFor="f-roll">Roll number</label><input id="f-roll" className="field" value={draft.roll_number} onChange={set("roll_number")} /></div>
          <div><label className="label" htmlFor="f-name">Name</label><input id="f-name" className="field" value={draft.name} onChange={set("name")} /></div>
          <div><label className="label" htmlFor="f-cam">Camera</label>
            <select id="f-cam" className="field" value={draft.camera_label} onChange={set("camera_label")}><option value="">All</option>{(cams.data ?? []).map((c) => <option key={c} value={c}>{c}</option>)}</select></div>
          <div><label className="label" htmlFor="f-dir">Direction</label>
            <select id="f-dir" className="field" value={draft.direction} onChange={set("direction")}><option value="">All</option><option value="ENTRY">Entry</option><option value="EXIT">Exit</option></select></div>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-6">
            <button type="submit" className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white">Apply filters</button>
            <button type="button" className="glass rounded-xl px-4 py-2 text-sm" onClick={() => { const e: Filters = { start_date: "", end_date: "", roll_number: "", name: "", camera_label: "", direction: "" }; setDraft(e); setApplied(e); setPage(1); }}>Reset</button>
          </div>
        </form>
      </GlassCard>
      <GlassTable data={q.data?.items ?? []} columns={attendanceColumns} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null}
        pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: setPage }} emptyTitle="No matching records" emptyDescription="Try widening the date range or clearing filters." caption="Attendance records" />
    </div>
  );
}

export default function SearchPage() { return <Suspense fallback={null}><SearchView /></Suspense>; }
