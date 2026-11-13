"use client";
import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ColumnDef } from "@tanstack/react-table";
import { api, errorMessage } from "@/lib/api";
import type { Analytics, LateArrival } from "@/lib/types";
import { ErrorNote, PageHeader } from "@/components/features/shared";
import { GlassChartCard, Skeleton, Tabs } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";
import { chartTooltip } from "@/lib/chart";

const lateCols: ColumnDef<LateArrival, unknown>[] = [{ accessorKey: "roll_number", header: "Roll no." }, { accessorKey: "name", header: "Name" }, { accessorKey: "timestamp", header: "Arrived" }];
const absentCols: ColumnDef<{ roll_number: string; name: string }, unknown>[] = [{ accessorKey: "roll_number", header: "Roll no." }, { accessorKey: "name", header: "Name" }];
const camCols: ColumnDef<Analytics["camera_stats"][number], unknown>[] = [{ accessorKey: "camera_label", header: "Camera" }, { accessorKey: "total", header: "Scans" }, { accessorKey: "unique_persons", header: "Unique people" }];

export default function AnalyticsPage() {
  const reduce = useReducedMotion();
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const q = useQuery({ queryKey: ["analytics", days], queryFn: () => api<Analytics>(`/analytics?days=${days}`) });
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Analytics" description="Attendance trends, peaks and exceptions" actions={<Tabs tabs={[{ id: "7", label: "7 days" }, { id: "30", label: "30 days" }, { id: "90", label: "90 days" }]} value={days} onChange={setDays} />} />
      <ErrorNote error={q.error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <GlassChartCard title="Daily attendance">{q.isLoading ? <Skeleton className="h-full w-full" /> : (
          <ResponsiveContainer><AreaChart data={d?.trends ?? []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="date" stroke="#949cb8" fontSize={11} /><YAxis allowDecimals={false} stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} />
            <Area type="monotone" dataKey="unique" stroke="rgb(34 211 238)" fill="rgb(34 211 238 / 0.25)" isAnimationActive={!reduce} /><Area type="monotone" dataKey="total" stroke="rgb(129 110 255)" fill="rgb(129 110 255 / 0.2)" isAnimationActive={!reduce} /></AreaChart></ResponsiveContainer>)}</GlassChartCard>
        <GlassChartCard title="Peak hours">{q.isLoading ? <Skeleton className="h-full w-full" /> : (
          <ResponsiveContainer><BarChart data={d?.peak_hours ?? []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="hour" stroke="#949cb8" fontSize={12} /><YAxis allowDecimals={false} stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} /><Bar dataKey="count" fill="rgb(34 211 238)" radius={[6, 6, 0, 0]} isAnimationActive={!reduce} /></BarChart></ResponsiveContainer>)}</GlassChartCard>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <div><h3 className="mb-2 text-sm font-semibold">Per camera</h3><GlassTable data={d?.camera_stats ?? []} columns={camCols} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null} /></div>
        <div><h3 className="mb-2 text-sm font-semibold">Absent today</h3><GlassTable data={d?.absent ?? []} columns={absentCols} loading={q.isLoading} emptyTitle="Nobody absent" /></div>
        <div><h3 className="mb-2 text-sm font-semibold">Late arrivals</h3><GlassTable data={d?.late_arrivals ?? []} columns={lateCols} loading={q.isLoading} emptyTitle="No late arrivals" /></div>
      </div>
    </div>
  );
}
