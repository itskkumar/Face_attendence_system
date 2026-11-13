"use client";
import { useQuery } from "@tanstack/react-query";
import { HelpCircle, ShieldAlert, UserCheck } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { api, errorMessage } from "@/lib/api";
import { useLiveFeed } from "@/lib/live-feed";
import type { LiveStatus, PadEventRow, SecurityAlerts } from "@/lib/types";
import { fmtPct } from "@/lib/utils";
import { EventFeed } from "@/components/features/event-feed";
import { LivePreview } from "@/components/features/live-preview";
import { ErrorNote, PadBanner, PageHeader, Section } from "@/components/features/shared";
import { GlassStatCard, StatusBadge } from "@/components/ui/glass";
import { GlassTable } from "@/components/ui/table";

const cols: ColumnDef<PadEventRow, unknown>[] = [
  { accessorKey: "timestamp", header: "Time" },
  { accessorKey: "camera_label", header: "Camera" },
  { accessorKey: "track_id", header: "Track" },
  { accessorKey: "state", header: "State", cell: ({ getValue }) => <StatusBadge color={getValue() === "SPOOF" ? "#ef4444" : getValue() === "LIVE" ? "#22c55e" : "#9ca3af"} label={String(getValue())} /> },
  { accessorKey: "real_prob", header: "Real prob.", cell: ({ getValue }) => fmtPct(getValue() as number | null, 0) },
  { accessorKey: "note", header: "Note" },
];

export default function MonitorPage() {
  const feed = useLiveFeed();
  const statusQ = useQuery({ queryKey: ["live-status"], queryFn: () => api<LiveStatus>("/live/status"), refetchInterval: 4000 });
  const alerts = useQuery({ queryKey: ["security-alerts"], queryFn: () => api<SecurityAlerts>("/security/alerts?limit=50"), refetchInterval: 10_000 });
  const status = feed.status ?? statusQ.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Security monitor" description="Live gate view, entries, unknown people and spoof alerts" actions={<StatusBadge color={status?.running ? "#22c55e" : "#9ca3af"} label={status?.running ? "Gate live" : "Gate stopped"} pulse={Boolean(status?.running)} />} />
      <ErrorNote error={statusQ.error ?? alerts.error} />
      {status && <PadBanner livenessMode={status.liveness_mode} pad={status.pad} />}
      <div className="grid grid-cols-3 gap-4">
        <GlassStatCard label="Entries (session)" value={status?.session_logged} icon={<UserCheck className="h-5 w-5" />} />
        <GlassStatCard label="Unknown today" value={alerts.data?.unknown_today} icon={<HelpCircle className="h-5 w-5" />} delay={0.05} />
        <GlassStatCard label="Spoof alerts today" value={alerts.data?.spoof_today} icon={<ShieldAlert className="h-5 w-5" />} delay={0.1} />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1fr_24rem]">
        <LivePreview active={Boolean(status?.running)} />
        <Section title="Recent entries & alerts"><EventFeed events={feed.events} limit={25} filter={(e) => ["attendance.recorded", "attendance.rejected", "identity.unknown", "liveness.failed", "review.required"].includes(e.type)} /></Section>
      </div>
      <div><h3 className="mb-2 text-sm font-semibold">Presentation-attack log</h3>
        <GlassTable data={alerts.data?.pad_events ?? []} columns={cols} loading={alerts.isLoading} error={alerts.error ? errorMessage(alerts.error) : null} emptyTitle="No PAD events" emptyDescription="Liveness decisions and flagged attacks appear here." /></div>
    </div>
  );
}
