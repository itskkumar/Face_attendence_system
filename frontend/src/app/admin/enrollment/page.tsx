"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Camera as CamIcon, CheckCircle2, ImageUp, XCircle } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api, errorMessage } from "@/lib/api";
import { grabJpeg, useCameraStream } from "@/lib/camera";
import type { EnrollmentStatus, SampleResult } from "@/lib/types";
import { fmtPct } from "@/lib/utils";
import { ErrorNote, PadBanner, PageHeader, Section } from "@/components/features/shared";
import { Field, GlassButton, Tabs } from "@/components/ui/glass";
import { useToast } from "@/components/ui/toast";

const schema = z.object({
  roll_number: z.string().trim().min(1, "Required"),
  name: z.string().trim().min(1, "Required"),
  email: z.string().trim().optional(),
  phone: z.string().trim().optional(),
  department: z.string().trim().optional(),
  batch: z.string().trim().optional(),
  expected_time: z.string().trim().optional(),
  mode: z.enum(["replace", "append"]),
});
type Values = z.infer<typeof schema>;

function ProgressRing({ value, total }: { value: number; total: number }) {
  const r = 28, c = 2 * Math.PI * r;
  return (
    <svg width="72" height="72" viewBox="0 0 72 72" role="img" aria-label={`${value} of ${total} samples`}>
      <circle cx="36" cy="36" r={r} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="6" />
      <motion.circle cx="36" cy="36" r={r} fill="none" stroke="rgb(34 211 238)" strokeWidth="6" strokeLinecap="round" transform="rotate(-90 36 36)"
        strokeDasharray={c} initial={false} animate={{ strokeDashoffset: c * (1 - Math.min(1, total ? value / total : 0)) }} transition={{ type: "spring", stiffness: 120, damping: 20 }} />
      <text x="36" y="41" textAnchor="middle" fontSize="16" fontWeight="600" fill="currentColor">{value}/{total}</text>
    </svg>
  );
}

function EnrollView() {
  const sp = useSearchParams();
  const { toast } = useToast();
  const statusQ = useQuery({ queryKey: ["enroll-status"], queryFn: () => api<EnrollmentStatus>("/enrollment/status") });
  const [tab, setTab] = useState<"camera" | "upload">("camera");
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { roll_number: sp.get("roll") ?? "", name: sp.get("name") ?? "", mode: sp.get("roll") ? "replace" : "append" } });

  const [session, setSession] = useState<{ id: string; target: number } | null>(null);
  const [count, setCount] = useState(0);
  const [results, setResults] = useState<SampleResult[]>([]);
  const [auto, setAuto] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ templates: number; liveness_verified: boolean } | null>(null);
  const cam = useCameraStream(session !== null && !done);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const st = statusQ.data;
  const blocked = Boolean(st && st.require_liveness && st.pad.state !== "READY");

  const begin = useMutation({
    mutationFn: (v: Values) => api<{ session_id: string; target_samples: number }>("/enrollment/session", { method: "POST", body: v }),
    onSuccess: (r) => { setSession({ id: r.session_id, target: r.target_samples }); setCount(0); setResults([]); setDone(null); },
    onError: (e) => toast({ title: "Could not start enrollment", description: errorMessage(e), variant: "error" }),
  });
  const finish = useMutation({
    mutationFn: () => api<{ ok: boolean; templates: number; liveness_verified: boolean }>(`/enrollment/session/${session!.id}/finish`, { method: "POST" }),
    onSuccess: (r) => { setDone(r); setAuto(false); toast({ title: "Enrollment saved", description: `${r.templates} template(s)`, variant: "success" }); },
    onError: (e) => toast({ title: "Could not finish", description: errorMessage(e), variant: "error" }),
  });
  const cancel = useMutation({
    mutationFn: () => api(`/enrollment/session/${session!.id}`, { method: "DELETE" }),
    onSettled: () => { setSession(null); setAuto(false); setCount(0); setResults([]); },
  });

  const capture = async () => {
    const s = sessionRef.current; const v = cam.videoRef.current;
    if (!s || !v || busy) return;
    setBusy(true);
    try {
      const blob = await grabJpeg(v, 960, 0.85);
      if (!blob) throw new Error("Camera not ready");
      const fd = new FormData(); fd.append("image", blob, "frame.jpg");
      const r = await api<SampleResult>(`/enrollment/session/${s.id}/sample`, { method: "POST", form: fd });
      setResults((p) => [r, ...p].slice(0, 8)); setCount(r.count);
      if (r.count >= r.target) setAuto(false);
    } catch (e) {
      setResults((p) => [{ accepted: false, reason: errorMessage(e), pad_state: null, pad_real_prob: null, count, target: s.target }, ...p].slice(0, 8));
      setAuto(false);
    } finally { setBusy(false); }
  };
  const captureRef = useRef(capture);
  captureRef.current = capture;
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => { void captureRef.current(); }, 1400);
    return () => clearInterval(t);
  }, [auto]);

  const [files, setFiles] = useState<File[]>([]);
  const upload = useMutation({
    mutationFn: (v: Values) => { const fd = new FormData(); fd.append("roll_number", v.roll_number); fd.append("name", v.name); fd.append("mode", v.mode); files.forEach((f) => fd.append("files", f)); return api<{ templates: number; rejected: { filename: string; reason: string }[] }>("/enrollment/photos", { method: "POST", form: fd }); },
    onSuccess: (r) => toast({ title: `Enrolled with ${r.templates} template(s)`, description: r.rejected.length ? `${r.rejected.length} photo(s) rejected` : "Liveness was not verified", variant: r.rejected.length ? "warning" : "success" }),
    onError: (e) => toast({ title: "Upload failed", description: errorMessage(e), variant: "error" }),
  });

  const errs = form.formState.errors;
  return (
    <div className="space-y-5">
      <PageHeader title="Enrollment" description="Capture quality-checked face samples; live samples must pass the anti-spoofing check" actions={<Tabs tabs={[{ id: "camera", label: "Live camera" }, { id: "upload", label: "Upload photos" }]} value={tab} onChange={setTab} />} />
      <ErrorNote error={statusQ.error} />
      {st && <PadBanner livenessMode={st.liveness_mode} pad={st.pad} />}
      {st && !st.engine_ready && <p role="alert" className="rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">The face engine is not ready on the server.</p>}

      <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
        <Section title="Student">
          <form className="space-y-3" noValidate onSubmit={(e) => e.preventDefault()}>
            <Field label="Roll number" disabled={session !== null} {...form.register("roll_number")} error={errs.roll_number?.message} />
            <Field label="Name" disabled={session !== null} {...form.register("name")} error={errs.name?.message} />
            <Field label="Email" type="email" disabled={session !== null} {...form.register("email")} />
            <Field label="Phone" disabled={session !== null} {...form.register("phone")} />
            <div className="grid grid-cols-2 gap-3"><Field label="Department" disabled={session !== null} {...form.register("department")} /><Field label="Batch" disabled={session !== null} {...form.register("batch")} /></div>
            <Field label="Expected time (HH:MM)" disabled={session !== null} {...form.register("expected_time")} />
            <div><label className="label" htmlFor="enr-mode">If the student already has templates</label>
              <select id="enr-mode" className="field" disabled={session !== null} {...form.register("mode")}><option value="append">Add to existing templates</option><option value="replace">Replace existing templates</option></select></div>
          </form>
        </Section>

        {tab === "camera" ? (
          <Section title="Camera capture">
            {blocked && <p role="alert" className="mb-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">Live enrollment is blocked: liveness verification is required but the PAD model is {st?.pad.state.replace("_", " ").toLowerCase()}. Use the photo upload path (recorded as "liveness not verified") or install the model.</p>}
            {!session ? (
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm text-muted">Start a session, face the camera, and capture 5 samples with small head turns. Each sample is checked for sharpness, pose, single face and liveness.</p>
                <GlassButton loading={begin.isPending} disabled={blocked || !st?.engine_ready} onClick={form.handleSubmit((v) => begin.mutate(v))}><CamIcon className="h-4 w-4" />Start session</GlassButton>
              </div>
            ) : done ? (
              <div className="space-y-3" role="status">
                <p className="flex items-center gap-2 text-lg font-semibold text-success"><CheckCircle2 className="h-5 w-5" />Enrolled with {done.templates} template(s)</p>
                {!done.liveness_verified && <p className="text-sm text-warn">Liveness was not verified for these samples.</p>}
                <GlassButton onClick={() => { setSession(null); setDone(null); setResults([]); setCount(0); }}>Enroll another student</GlassButton>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="relative overflow-hidden rounded-xl2 bg-black">
                  <video ref={cam.videoRef} muted playsInline className="aspect-video w-full object-cover" aria-label="Enrollment camera" />
                  {cam.active && <div aria-hidden className="pointer-events-none absolute left-0 right-0 h-0.5 animate-scan bg-accent shadow-[0_0_18px_rgb(34_211_238)]" />}
                  <div className="absolute right-3 top-3 rounded-2xl bg-black/50 p-1 text-white"><ProgressRing value={count} total={session.target} /></div>
                  {busy && <div className="absolute bottom-3 left-3 rounded-full bg-black/60 px-3 py-1 text-xs text-white" role="status">Analysing...</div>}
                </div>
                {cam.error && <p role="alert" className="text-sm text-danger">{cam.error}</p>}
                <div className="flex flex-wrap gap-2">
                  <GlassButton onClick={() => void capture()} disabled={!cam.active || busy}>Capture sample</GlassButton>
                  <GlassButton variant="subtle" onClick={() => setAuto((a) => !a)} disabled={!cam.active}>{auto ? "Stop auto-capture" : "Auto-capture"}</GlassButton>
                  <GlassButton variant="primary" loading={finish.isPending} disabled={count < 1} onClick={() => finish.mutate()}>Finish ({count}/{session.target})</GlassButton>
                  <GlassButton variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel</GlassButton>
                </div>
                <ul className="space-y-1.5" aria-live="polite">
                  {results.map((r, i) => (
                    <motion.li key={`${i}-${r.count}-${r.reason}`} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className="flex items-start gap-2 text-sm">
                      {r.accepted ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />}
                      <span>{r.accepted ? "Sample accepted" : r.reason || "Rejected"}{r.pad_state ? ` | liveness ${r.pad_state}${r.pad_real_prob !== null ? ` ${fmtPct(r.pad_real_prob)}` : ""}` : ""}</span>
                    </motion.li>))}
                </ul>
              </div>
            )}
          </Section>
        ) : (
          <Section title="Upload photos (admin only)">
            <p className="mb-3 rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn">Photos cannot be liveness-checked. The enrollment is audit-logged and recorded as "liveness not verified". A spoofed photo here would enroll a spoofed face, so use this only for people you have verified in person.</p>
            <label className="label" htmlFor="enr-files">1 to 8 clear, frontal photos</label>
            <input id="enr-files" type="file" accept="image/*" multiple className="field" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 8))} />
            {files.length > 0 && <p className="mt-2 text-xs text-muted">{files.length} file(s) selected</p>}
            <GlassButton className="mt-4" disabled={files.length === 0} loading={upload.isPending} onClick={form.handleSubmit((v) => upload.mutate(v))}><ImageUp className="h-4 w-4" />Enroll from photos</GlassButton>
            {upload.data && upload.data.rejected.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-danger">{upload.data.rejected.map((r) => <li key={r.filename}>{r.filename}: {r.reason}</li>)}</ul>}
          </Section>
        )}
      </div>
    </div>
  );
}

export default function EnrollmentPage() { return <Suspense fallback={null}><EnrollView /></Suspense>; }
