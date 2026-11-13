"use client";
import { motion, useReducedMotion } from "framer-motion";
import { CheckCircle2, ShieldAlert, VideoOff } from "lucide-react";
import { useCallback, useState } from "react";
import { statusColor } from "@/lib/status";
import type { PreviewFrame, Track } from "@/lib/types";
import { cn, fmtPct } from "@/lib/utils";
import { useReconnectingSocket } from "@/lib/ws";
import { EmptyState, StatusBadge } from "@/components/ui/glass";

function Box({ t, w, h }: { t: Track; w: number; h: number }) {
  const reduce = useReducedMotion();
  const [x1, y1, x2, y2] = t.bbox;
  const color = statusColor(t.status);
  const spoof = t.status === "POSSIBLE SPOOF";
  const done = t.status === "ATTENDANCE RECORDED";
  return (
    <motion.div
      className={cn("absolute rounded-md border-2", spoof && "animate-spoof")}
      style={{ borderColor: color, boxShadow: `0 0 18px ${color}55` }}
      initial={false}
      animate={{ left: `${(x1 / w) * 100}%`, top: `${(y1 / h) * 100}%`, width: `${((x2 - x1) / w) * 100}%`, height: `${((y2 - y1) / h) * 100}%` }}
      transition={reduce ? { duration: 0 } : { duration: 0.12, ease: "linear" }}
    >
      <motion.div initial={reduce ? false : { opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
        className="absolute bottom-full left-[-2px] mb-1 flex max-w-[16rem] flex-col gap-0.5 rounded-lg px-2 py-1 text-[11px] leading-tight text-white"
        style={{ background: `${color}e6` }}>
        <span className="flex items-center gap-1 font-semibold">
          {spoof && <ShieldAlert className="h-3 w-3" />}
          {done && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 500, damping: 18 }}><CheckCircle2 className="h-3 w-3" /></motion.span>}
          {t.status}
        </span>
        <span>#{t.track_id}{t.name ? ` ${t.name}` : ""}{t.roll_number ? ` (${t.roll_number})` : ""}</span>
        <span className="opacity-90">
          {t.det_score !== null ? `det ${t.det_score.toFixed(2)}` : ""}{t.similarity !== null ? ` | sim ${t.similarity.toFixed(2)}` : ""}
          {t.pad_real_prob !== null ? ` | real ${fmtPct(t.pad_real_prob)}` : ""}{t.pad_state ? ` ${t.pad_state}` : ""}
        </span>
      </motion.div>
    </motion.div>
  );
}

/** Annotated preview from /ws/preview. The server only sends frames while this component is connected. */
export function LivePreview({ active, className }: { active: boolean; className?: string }) {
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  const onMessage = useCallback((m: unknown) => {
    const f = m as PreviewFrame;
    if (f && f.kind === "frame") setFrame(f);
  }, []);
  const { state, attempts } = useReconnectingSocket("/ws/preview", { enabled: active, onMessage });

  if (!active) return <div className={cn("glass rounded-xl2", className)}><EmptyState icon={<VideoOff className="h-5 w-5" />} title="Camera is not running" description="Start a source to see the live preview." /></div>;
  return (
    <div className={cn("glass relative overflow-hidden rounded-xl2", className)}>
      {frame ? (
        <div className="relative w-full" style={{ aspectRatio: `${frame.width} / ${frame.height}` }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img alt="Live camera preview with face annotations" className="absolute inset-0 h-full w-full object-fill" src={`data:image/jpeg;base64,${frame.jpeg_b64}`} />
          {frame.tracks.map((t) => <Box key={t.track_id} t={t} w={frame.width} h={frame.height} />)}
          <div className="absolute left-3 top-3 flex items-center gap-2">
            <StatusBadge color="#ef4444" label="LIVE" pulse />
            <span className="rounded-full bg-black/55 px-2 py-0.5 text-xs text-white tabular-nums">{frame.fps.toFixed(1)} fps | {frame.proc_ms.toFixed(0)} ms</span>
          </div>
        </div>
      ) : (
        <div className="flex aspect-video items-center justify-center text-sm text-muted" role="status">
          {state === "failed" ? "Preview denied by the server" : state === "reconnecting" ? `Reconnecting (attempt ${attempts})...` : "Waiting for the first frame..."}
        </div>
      )}
      {frame && state !== "open" && <div role="status" className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-xs text-white">Reconnecting...</div>}
    </div>
  );
}
