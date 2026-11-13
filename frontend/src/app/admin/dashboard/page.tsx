"use client";
import { useQuery } from "@tanstack/react-query";
import { Activity, HelpCircle, UserCheck, Users, UserX } from "lucide-react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useReducedMotion } from "framer-motion";
import type { ColumnDef } from "@tanstack/react-table";
import { api, errorMessage } from "@/lib/api";
import { chartTooltip } from "@/lib/chart";
import type { Dashboard, LateArrival } from "@/lib/types";
import { ErrorNote, PageHeader, Section } from "@/components/features/shared";
import { attendanceColumns } from "@/components/features/columns";
import { GlassChartCard, GlassStatCard, Skeleton } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";

const lateCols: ColumnDef<LateArrival, unknown>[] = [
  { accessorKey: "roll_number", header: "Roll no." }, { accessorKey: "name", header: "Name" }, { accessorKey: "timestamp", header: "Arrived" },
];

export default function DashboardPage() {
  const reduce = useReducedMotion();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchInterval: 15_000 });
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Dashboard" description="Today's attendance at a glance" />
      <ErrorNote error={q.error} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <GlassStatCard label="Unique today" value={d?.today_unique} icon={<UserCheck className="h-5 w-5" />} />
        <GlassStatCard label="Scans today" value={d?.today_scans} icon={<Activity className="h-5 w-5" />} delay={0.05} />
        <GlassStatCard label="Known" value={d?.today_known} icon={<Users className="h-5 w-5" />} delay={0.1} />
        <GlassStatCard label="Unknown" value={d?.today_unknown} icon={<HelpCircle className="h-5 w-5" />} delay={0.15} />
        <GlassStatCard label="Enrolled" value={d?.enrolled_students} icon={<UserX className="h-5 w-5" />} delay={0.2} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <GlassChartCard title="Hourly attendance (today)">
          {q.isLoading ? <Skeleton className="h-full w-full" /> : (
            <ResponsiveContainer><BarChart data={d?.hourly ?? []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="hour" stroke="#949cb8" fontSize={12} /><YAxis allowDecimals={false} stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} /><Bar dataKey="count" fill="rgb(129 110 255)" radius={[6, 6, 0, 0]} isAnimationActive={!reduce} /></BarChart></ResponsiveContainer>
          )}
        </GlassChartCard>
        <GlassChartCard title="30-day trend" subtitle="Unique students and total scans per day">
          {q.isLoading ? <Skeleton className="h-full w-full" /> : (
            <ResponsiveContainer><AreaChart data={d?.trends ?? []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="date" stroke="#949cb8" fontSize={11} /><YAxis allowDecimals={false} stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} />
              <Area type="monotone" dataKey="unique" stroke="rgb(34 211 238)" fill="rgb(34 211 238 / 0.25)" isAnimationActive={!reduce} />
              <Area type="monotone" dataKey="total" stroke="rgb(129 110 255)" fill="rgb(129 110 255 / 0.2)" isAnimationActive={!reduce} /></AreaChart></ResponsiveContainer>
          )}
        </GlassChartCard>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Peak hours">
          {(d?.peak_hours ?? []).length === 0 ? <p className="text-sm text-muted">No data yet.</p> : (
            <ul className="space-y-2 text-sm">{d!.peak_hours.map((p) => (<li key={p.hour} className="flex justify-between"><span>{String(p.hour).padStart(2, "0")}:00</span><span className="tabular-nums text-muted">{p.count} scans</span></li>))}</ul>
          )}
        </Section>
        <div className="lg:col-span-2"><h3 className="mb-2 text-sm font-semibold">Late arrivals today</h3><GlassTable data={d?.late_arrivals ?? []} columns={lateCols} loading={q.isLoading} emptyTitle="No late arrivals today" /></div>
      </div>
      <div><h3 className="mb-2 text-sm font-semibold">Recent activity</h3>
        <GlassTable data={d?.recent ?? []} columns={attendanceColumns} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null} emptyTitle="No attendance recorded yet" /></div>
    </div>
  );
}
