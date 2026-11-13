"use client";
import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { CalendarDays, CalendarRange, Percent, Sun } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, errorMessage } from "@/lib/api";
import { chartTooltip } from "@/lib/chart";
import type { AttendanceRow } from "@/lib/types";
import { ErrorNote, PageHeader } from "@/components/features/shared";
import { attendanceColumns } from "@/components/features/columns";
import { GlassChartCard, GlassStatCard, Skeleton } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";

interface Summary { today: AttendanceRow[]; week_count: number; month_count: number; attendance_percentage_30d: number; trends: { date: string; count: number }[] }

export default function StudentDashboard() {
  const reduce = useReducedMotion();
  const q = useQuery({ queryKey: ["me-summary"], queryFn: () => api<Summary>("/me/summary") });
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="My dashboard" description="Your own attendance" />
      <ErrorNote error={q.error} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <GlassStatCard label="Today" value={d?.today.length} icon={<Sun className="h-5 w-5" />} />
        <GlassStatCard label="This week" value={d?.week_count} icon={<CalendarDays className="h-5 w-5" />} delay={0.05} />
        <GlassStatCard label="This month" value={d?.month_count} icon={<CalendarRange className="h-5 w-5" />} delay={0.1} />
        <GlassStatCard label="Attendance (30 days)" value={d?.attendance_percentage_30d} suffix="%" decimals={1} icon={<Percent className="h-5 w-5" />} delay={0.15} />
      </div>
      <GlassChartCard title="Daily check-ins">
        {q.isLoading ? <Skeleton className="h-full w-full" /> : (
          <ResponsiveContainer><BarChart data={d?.trends ?? []}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="date" stroke="#949cb8" fontSize={11} /><YAxis allowDecimals={false} stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} /><Bar dataKey="count" fill="rgb(129 110 255)" radius={[6, 6, 0, 0]} isAnimationActive={!reduce} /></BarChart></ResponsiveContainer>)}
      </GlassChartCard>
      <div><h3 className="mb-2 text-sm font-semibold">Today</h3><GlassTable data={d?.today ?? []} columns={attendanceColumns.slice(0, 4)} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null} emptyTitle="No check-in recorded today" /></div>
    </div>
  );
}
