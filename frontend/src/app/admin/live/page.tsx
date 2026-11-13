"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { grabJpeg, useCameraStream } from "@/lib/camera";
import { useLiveFeed } from "@/lib/live-feed";
import type { Camera, LiveStatus, Tuning } from "@/lib/types";
import { fmtMs } from "@/lib/utils";
import { useReconnectingSocket } from "@/lib/ws";
import { EventFeed } from "@/components/features/event-feed";
import { LivePreview } from "@/components/features/live-preview";
import { ErrorNote, PadBanner, PageHeader, Section } from "@/components/features/shared";
import { GlassButton, StatusBadge } from "@/components/ui/glass";
import { useToast } from "@/components/ui/toast";

type SourceKind = "server_webcam" | "camera" | "file" | "browser";

function Slider({ label, value, min, max, step, onChange, disabled }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; disabled?: boolean }) {
  const id = `sl-${label.replace(/\W+/g, "-")}`;
  return (
    <div>
      <div className="flex justify-between"><label htmlFor={id} className="label">{label}</label><span className="text-xs tabular-nums">{value}</span></div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} className="w-full accent-[rgb(var(--primary))]" />
    </div>
  );
}

export default function LivePage() {
  const { user } = useAuth();
  const canControl = user?.role === "admin";
  const qc = useQueryClient();
  const { toast } = useToast();
  const feed = useLiveFeed();
  const statusQ = useQuery({ queryKey: ["live-status"], queryFn: () => api<LiveStatus>("/live/status"), refetchInterval: 4000 });
  const camsQ = useQuery({ queryKey: ["cameras"], queryFn: () => api<Camera[]>("/cameras") });
  const status = feed.status ?? statusQ.data;

  const [kind, setKind] = useState<SourceKind>("server_webcam");
  const [webcamIndex, setWebcamIndex] = useState(0);
  const [cameraId, setCameraId] = useState("");
  const [filePath, setFilePath] = useState("");
  const [loop, setLoop] = useState(true);
  const [label, setLabel] = useState("");
  const [tuning, setTuning] = useState<Tuning | null>(null);
  const [browserActive, setBrowserActive] = useState(false);

  useEffect(() => { if (status && !tuning) setTuning(status.settings); }, [status, tuning]);
  useEffect(() => { if (!cameraId && camsQ.data?.length) setCameraId(camsQ.data.find((c) => c.enabled)?.id ?? ""); }, [camsQ.data, cameraId]);

  const refresh = () => { void qc.invalidateQueries({ queryKey: ["live-status"] }); };
  const start = useMutation({
    mutationFn: () => api<LiveStatus>("/live/start", { method: "POST", body: {
      source: kind, webcam_index: kind === "server_webcam" ? webcamIndex : undefined, camera_id: kind === "camera" ? cameraId : undefined,
      file_path: kind === "file" ? filePath : undefined, loop: kind === "file" ? loop : undefined, camera_label: label || undefined, settings: tuning ?? undefined } }),
    onSuccess: () => { setBrowserActive(kind === "browser"); toast({ title: "Source started", variant: "success" }); refresh(); },
    onError: (e) => toast({ title: "Could not start", description: errorMessage(e), variant: "error" }),
  });
  const stop = useMutation({
    mutationFn: () => api<LiveStatus>("/live/stop", { method: "POST" }),
    onSuccess: () => { setBrowserActive(false); toast({ title: "Stopped", variant: "info" }); refresh(); },
    onError: (e) => toast({ title: "Could not stop", description: errorMessage(e), variant: "error" }),
  });
  const apply = useMutation({
    mutationFn: () => api<LiveStatus>("/live/settings", { method: "PUT", body: tuning }),
    onSuccess: () => { toast({ title: "Settings applied", variant: "success" }); refresh(); },
    onError: (e) => toast({ title: "Could not apply settings", description: errorMessage(e), variant: "error" }),
  });
  const upload = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api<{ file_path: string }>("/live/upload-video", { method: "POST", form: fd }); },
    onSuccess: (r) => { setFilePath(r.file_path); toast({ title: "Video uploaded", variant: "success" }); },
    onError: (e) => toast({ title: "Upload failed", description: errorMessage(e), variant: "error" }),
  });

  // ---- browser webcam: getUserMedia -> JPEG -> /ws/browser-camera (<= ~8 fps, width <= 960)
  const running = Boolean(status?.running);
  const sendingBrowser = browserActive && running;
  const { videoRef, error: camError } = useCameraStream(sendingBrowser);
  const dropped = useRef(0);
  const onAck = useCallback((m: unknown) => { const a = m as { kind?: string; dropped?: number }; if (a.kind === "ack" && typeof a.dropped === "number") dropped.current = a.dropped; }, []);
  const sock = useReconnectingSocket("/ws/browser-camera", { enabled: sendingBrowser, onMessage: onAck });
  const sockRef = useRef(sock);
  sockRef.current = sock;
  useEffect(() => {
    if (!sendingBrowser) return;
    let busy = false;
    const t = setInterval(async () => {
      const v = videoRef.current;
      const s = sockRef.current;
      if (busy || !v || s.state !== "open" || s.bufferedAmount() > 400_000) return;
      busy = true;
      try { const blob = await grabJpeg(v, 960, 0.7); if (blob) s.send(blob); } finally { busy = false; }
    }, 125);
    return () => clearInterval(t);
  }, [sendingBrowser, videoRef]);

  const setT = <K extends keyof Tuning>(k: K, v: Tuning[K]) => setTuning((p) => (p ? { ...p, [k]: v } : p));

  return (
    <div className="space-y-5">
      <PageHeader title="Live feed" description={canControl ? "Start a source, tune the gate and watch recognition and liveness in real time" : "Read-only view: only administrators can start, stop or tune the gate"}
        actions={<StatusBadge color={running ? "#22c55e" : "#9ca3af"} label={running ? `Running: ${status?.source_label}` : "Stopped"} pulse={running} />} />
      <ErrorNote error={statusQ.error} />
      {status && <PadBanner livenessMode={status.liveness_mode} pad={status.pad} />}
      {status?.error && <p role="alert" className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">Worker error: {status.error}</p>}

      <div className="grid gap-5 xl:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <LivePreview active={running} />
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:grid-cols-7">
            {([["FPS", status ? status.fps.toFixed(1) : "-"], ["Frame", fmtMs(status?.proc_ms)], ["Detect", fmtMs(status?.det_ms)], ["Recognise", fmtMs(status?.rec_ms)], ["PAD", fmtMs(status?.pad_ms)], ["Faces", status?.faces ?? "-"], ["Logged", status?.session_logged ?? "-"]] as [string, string | number][]).map(([k, v]) => (
              <div key={k} className="glass rounded-xl px-3 py-2"><p className="text-[11px] uppercase text-muted">{k}</p><p className="font-semibold tabular-nums">{v}</p></div>
            ))}
          </div>
          {sendingBrowser && (
            <div className="glass rounded-xl2 p-3">
              <p className="mb-2 text-xs text-muted">Your browser camera (frames are sent to the server; stop to release the camera)</p>
              <video ref={videoRef} muted playsInline className="max-h-40 rounded-xl" aria-label="Local camera" />
              {camError && <p role="alert" className="mt-2 text-sm text-danger">{camError}</p>}
              <p className="mt-1 text-xs text-muted">Upload socket: {sock.state}{dropped.current ? ` | server dropped ${dropped.current} stale frames` : ""}</p>
            </div>
          )}
          <Section title="Events"><EventFeed events={feed.events} limit={20} /></Section>
        </div>

        <div className="space-y-4">
          <Section title="Source">
            <div className="space-y-3">
              <div><label className="label" htmlFor="src-kind">Source</label>
                <select id="src-kind" className="field" value={kind} disabled={!canControl || running} onChange={(e) => setKind(e.target.value as SourceKind)}>
                  <option value="server_webcam">Server webcam</option><option value="camera">Configured camera (RTSP)</option><option value="file">Video file</option><option value="browser">Browser webcam</option>
                </select></div>
              {kind === "server_webcam" && <div><label className="label" htmlFor="src-idx">Webcam index</label><input id="src-idx" type="number" min={0} max={9} className="field" value={webcamIndex} disabled={!canControl || running} onChange={(e) => setWebcamIndex(Number(e.target.value))} /></div>}
              {kind === "camera" && <div><label className="label" htmlFor="src-cam">Camera</label>
                <select id="src-cam" className="field" value={cameraId} disabled={!canControl || running} onChange={(e) => setCameraId(e.target.value)}>
                  {(camsQ.data ?? []).filter((c) => c.enabled).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                {camsQ.data && camsQ.data.filter((c) => c.enabled).length === 0 && <p className="mt-1 text-xs text-warn">No enabled cameras. Add one on the Cameras page.</p>}</div>}
              {kind === "file" && <>
                <div><label className="label" htmlFor="src-file">Server file path</label><input id="src-file" className="field" value={filePath} disabled={!canControl || running} onChange={(e) => setFilePath(e.target.value)} placeholder="/path/to/video.mp4" /></div>
                <div><label className="label" htmlFor="src-up">...or upload a video</label><input id="src-up" type="file" accept="video/*" className="field" disabled={!canControl || running || upload.isPending} onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} /></div>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={loop} disabled={!canControl || running} onChange={(e) => setLoop(e.target.checked)} />Loop video</label></>}
              <div><label className="label" htmlFor="src-label">Camera label (optional)</label><input id="src-label" className="field" value={label} disabled={!canControl || running} onChange={(e) => setLabel(e.target.value)} placeholder="Main gate" /></div>
              {canControl && (running
                ? <GlassButton variant="danger" className="w-full" loading={stop.isPending} onClick={() => stop.mutate()}><Square className="h-4 w-4" />Stop</GlassButton>
                : <GlassButton className="w-full" loading={start.isPending} disabled={(kind === "file" && !filePath) || (kind === "camera" && !cameraId)} onClick={() => start.mutate()}><Play className="h-4 w-4" />Start</GlassButton>)}
            </div>
          </Section>

          <Section title="Gate tuning">
            {!tuning ? <p className="text-sm text-muted">Loading settings...</p> : (
              <div className="space-y-3">
                <Slider label="Similarity threshold" value={tuning.similarity_threshold} min={0.2} max={0.9} step={0.01} disabled={!canControl} onChange={(v) => setT("similarity_threshold", v)} />
                <Slider label="Min sharpness (blur)" value={tuning.min_blur_var} min={0} max={300} step={5} disabled={!canControl} onChange={(v) => setT("min_blur_var", v)} />
                <Slider label="Min frontal pose" value={tuning.min_pose_score} min={0} max={1} step={0.05} disabled={!canControl} onChange={(v) => setT("min_pose_score", v)} />
                <Slider label="Detect every N frames" value={tuning.detect_every_n} min={1} max={10} step={1} disabled={!canControl} onChange={(v) => setT("detect_every_n", v)} />
                <Slider label="Cooldown (s)" value={tuning.cooldown_seconds} min={0} max={600} step={5} disabled={!canControl} onChange={(v) => setT("cooldown_seconds", v)} />
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tuning.gate_line_enabled} disabled={!canControl} onChange={(e) => setT("gate_line_enabled", e.target.checked)} />Gate line</label>
                {tuning.gate_line_enabled && <>
                  <div><label className="label" htmlFor="gl-o">Gate line orientation</label><select id="gl-o" className="field" value={tuning.gate_line_orientation} disabled={!canControl} onChange={(e) => setT("gate_line_orientation", e.target.value)}><option value="horizontal">Horizontal</option><option value="vertical">Vertical</option></select></div>
                  <Slider label="Gate line position" value={tuning.gate_line_ratio} min={0.1} max={0.9} step={0.05} disabled={!canControl} onChange={(v) => setT("gate_line_ratio", v)} /></>}
                <div><label className="label" htmlFor="liv">Liveness mode</label>
                  <select id="liv" className="field" value={tuning.liveness_mode} disabled={!canControl} onChange={(e) => setT("liveness_mode", e.target.value as Tuning["liveness_mode"])}>
                    <option value="off">Off (no anti-spoofing)</option><option value="fft_experimental">FFT experimental (unvalidated)</option><option value="minifas">MiniFASNet PAD</option></select>
                  {tuning.liveness_mode === "minifas" && status?.pad.state !== "READY" && <p className="mt-1 text-xs text-danger">PAD is {status?.pad.state ?? "unknown"}: attendance will be withheld.</p>}</div>
                {canControl && <GlassButton variant="subtle" className="w-full" loading={apply.isPending} onClick={() => apply.mutate()}>Apply settings</GlassButton>}
                {canControl && running && <p className="text-xs text-muted">Applying restarts the pipeline; the camera stays connected.</p>}
              </div>)}
          </Section>
        </div>
      </div>
    </div>
  );
}
