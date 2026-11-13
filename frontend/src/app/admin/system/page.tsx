"use client";
import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { Cpu, Gauge, MemoryStick, Timer } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import type { SystemInfo } from "@/lib/types";
import { ErrorNote, KeyValue, PadBanner, PageHeader, Section } from "@/components/features/shared";
import { GlassChartCard, GlassStatCard, StatusBadge } from "@/components/ui/glass";
import { fmtMs } from "@/lib/utils";
import { chartTooltip } from "@/lib/chart";

export default function SystemPage() {
  const reduce = useReducedMotion();
  const q = useQuery({ queryKey: ["system"], queryFn: () => api<SystemInfo>("/system"), refetchInterval: 3000 });
  const d = q.data;
  const series = (rows: [number, number][] | undefined, key: string) => (rows ?? []).map(([t, v]) => ({ t: new Date(t * 1000).toLocaleTimeString(), [key]: v }));
  const merged = d ? series(d.history.cpu, "cpu").map((r, i) => ({ ...r, ram: d.history.ram[i]?.[1], fps: d.history.fps[i]?.[1] })) : [];
  return (
    <div className="space-y-5">
      <PageHeader title="System health" description="Live host and pipeline metrics (no GPU / Neural Engine figures are reported)" actions={d && <StatusBadge color={d.worker_running ? "#22c55e" : "#9ca3af"} label={d.worker_running ? "Worker running" : "Worker idle"} />} />
      <ErrorNote error={q.error} />
      {d && <PadBanner livenessMode={d.liveness_mode} pad={d.pad} />}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <GlassStatCard label="CPU" value={d?.cpu_percent} suffix="%" decimals={0} icon={<Cpu className="h-5 w-5" />} />
        <GlassStatCard label="Memory" value={d?.ram_percent} suffix="%" icon={<MemoryStick className="h-5 w-5" />} hint={d ? `${d.ram_used_mb.toFixed(0)} MB used` : undefined} />
        <GlassStatCard label="FPS" value={d?.fps} decimals={1} icon={<Gauge className="h-5 w-5" />} />
        <GlassStatCard label="Frame latency" value={d?.proc_ms} suffix="ms" decimals={0} icon={<Timer className="h-5 w-5" />} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Pipeline"><KeyValue rows={[["Provider", d?.provider ?? "-"], ["Detect", fmtMs(d?.det_ms)], ["Recognise", fmtMs(d?.rec_ms)], ["PAD", fmtMs(d?.pad_ms)], ["Liveness mode", d?.liveness_mode ?? "-"], ["Database", d ? `${d.db_size_mb.toFixed(2)} MB` : "-"]]} /></Section>
        <Section title="PAD health"><KeyValue rows={[["State", d?.pad.state ?? "-"], ["Model", d?.pad.model_id || "none"], ["Provider", d?.pad.provider || "-"], ["Reason", d?.pad.reason || "-"]]} /></Section>
        <Section title="Alerts">
          {(d?.alerts ?? []).length === 0 ? <p className="text-sm text-muted">No alerts.</p> : (
            <ul className="space-y-2 text-sm">{d!.alerts.map((a, i) => (<li key={i} className="flex items-start gap-2"><StatusBadge color={a.level === "error" ? "#ef4444" : a.level === "warning" ? "#eab308" : "#3b82f6"} label={a.level} /><span>{a.message}</span></li>))}</ul>)}
        </Section>
      </div>
      <GlassChartCard title="Recent history" subtitle="CPU %, memory % and FPS">
        <ResponsiveContainer><LineChart data={merged}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="t" stroke="#949cb8" fontSize={11} /><YAxis stroke="#949cb8" fontSize={12} /><Tooltip {...chartTooltip} />
          <Line dataKey="cpu" stroke="rgb(129 110 255)" dot={false} isAnimationActive={!reduce} /><Line dataKey="ram" stroke="rgb(34 211 238)" dot={false} isAnimationActive={!reduce} /><Line dataKey="fps" stroke="rgb(34 197 94)" dot={false} isAnimationActive={!reduce} /></LineChart></ResponsiveContainer>
      </GlassChartCard>
    </div>
  );
}
