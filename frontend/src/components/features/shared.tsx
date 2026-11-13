"use client";
import { AlertTriangle, ShieldCheck, ShieldOff } from "lucide-react";
import type { ReactNode } from "react";
import { GlassCard, StatusBadge } from "@/components/ui/glass";
import type { PadHealth } from "@/lib/types";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h2 className="text-2xl font-semibold">{title}</h2>{description && <p className="text-sm text-muted">{description}</p>}</div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <p role="alert" className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{error instanceof Error ? error.message : "Something went wrong"}</p>;
}

/** Honest anti-spoofing status. Never implies protection that is not active. */
export function PadBanner({ livenessMode, pad }: { livenessMode: string; pad: PadHealth | undefined }) {
  if (livenessMode === "off") {
    return (
      <div role="alert" className="flex items-start gap-3 rounded-xl border border-warn/50 bg-warn/10 px-4 py-3 text-sm">
        <ShieldOff className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
        <div><p className="font-semibold text-warn">Anti-spoofing OFF</p><p className="text-muted">A printed photo or a phone screen showing a student can be accepted. Switch liveness mode to "minifas" once the PAD model is installed.</p></div>
      </div>
    );
  }
  if (livenessMode === "fft_experimental") {
    return (
      <div role="alert" className="flex items-start gap-3 rounded-xl border border-warn/50 bg-warn/10 px-4 py-3 text-sm">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
        <div><p className="font-semibold text-warn">FFT liveness is experimental and unvalidated</p><p className="text-muted">It is a screen-moire heuristic. It cannot prove a face is live and is not a substitute for the MiniFASNet PAD.</p></div>
      </div>
    );
  }
  if (!pad || pad.state !== "READY") {
    return (
      <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/50 bg-danger/10 px-4 py-3 text-sm">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-danger" />
        <div><p className="font-semibold text-danger">PAD {pad ? pad.state.replace("_", " ") : "status unknown"}</p>
          <p className="text-muted">{pad?.reason || "No status reported."} Attendance is withheld until the anti-spoofing model validates (see MODELS.json).</p></div>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-3 rounded-xl border border-success/40 bg-success/10 px-4 py-2.5 text-sm">
      <ShieldCheck className="h-5 w-5 text-success" />
      <span>Anti-spoofing active: <span className="font-medium">MiniFASNet</span> <span className="text-muted">({pad.model_id}{pad.provider ? `, ${pad.provider}` : ""})</span></span>
    </div>
  );
}

export function PadChip({ health }: { health: PadHealth | undefined }) {
  if (!health) return <StatusBadge color="#9ca3af" label="PAD unknown" />;
  const c = health.state === "READY" ? "#22c55e" : health.state === "ERROR" ? "#ef4444" : "#9ca3af";
  return <StatusBadge color={c} label={`PAD ${health.state.replace("_", " ")}`} />;
}

export function KeyValue({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
      {rows.map(([k, v]) => (<div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-words text-right font-medium tabular-nums">{v}</dd></div>))}
    </dl>
  );
}

export function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return <GlassCard className={className}><h3 className="mb-3 text-sm font-semibold">{title}</h3>{children}</GlassCard>;
}
