"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera as CamIcon, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Camera } from "@/lib/types";
import { ErrorNote, PageHeader } from "@/components/features/shared";
import { EmptyState, Field, GlassButton, GlassCard, Skeleton, StatusBadge } from "@/components/ui/glass";
import { GlassModal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";

const schema = z.object({
  name: z.string().trim().min(1, "Required"),
  type: z.enum(["rtsp", "webcam", "file", "http"]),
  source: z.string().trim(),
  description: z.string().trim(),
  enabled: z.boolean(),
});
type Values = z.infer<typeof schema>;

const STATUS_COLOR = { live: "#22c55e", idle: "#9ca3af", error: "#ef4444" } as const;

export default function CamerasPage() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [editing, setEditing] = useState<Camera | "new" | null>(null);
  const [deleting, setDeleting] = useState<Camera | null>(null);
  const q = useQuery({ queryKey: ["cameras"], queryFn: () => api<Camera[]>("/cameras"), refetchInterval: 5000 });
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { name: "", type: "rtsp", source: "", description: "", enabled: true } });
  const refresh = () => qc.invalidateQueries({ queryKey: ["cameras"] });

  const openEdit = (c: Camera | "new") => {
    setEditing(c);
    form.reset(c === "new" ? { name: "", type: "rtsp", source: "", description: "", enabled: true } : { name: c.name, type: c.type, source: "", description: c.description, enabled: c.enabled });
  };
  const save = useMutation({
    mutationFn: (v: Values) => {
      const body = editing !== "new" && !v.source ? { name: v.name, type: v.type, description: v.description, enabled: v.enabled } : v;
      return editing === "new" ? api<Camera>("/cameras", { method: "POST", body }) : api<Camera>(`/cameras/${encodeURIComponent((editing as Camera).id)}`, { method: "PUT", body });
    },
    onSuccess: () => { toast({ title: "Camera saved", variant: "success" }); setEditing(null); void refresh(); },
    onError: (e) => toast({ title: "Could not save camera", description: errorMessage(e), variant: "error" }),
  });
  const del = useMutation({
    mutationFn: (c: Camera) => api(`/cameras/${encodeURIComponent(c.id)}`, { method: "DELETE" }),
    onSuccess: () => { toast({ title: "Camera deleted", variant: "success" }); setDeleting(null); void refresh(); },
    onError: (e) => toast({ title: "Could not delete camera", description: errorMessage(e), variant: "error" }),
  });
  const submit = form.handleSubmit((v) => {
    if (editing === "new" && !v.source) { form.setError("source", { message: "Required for a new camera" }); return; }
    save.mutate(v);
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Cameras" description="Configured sources. Credentials in stream URLs are masked and never leave the server."
        actions={admin && <GlassButton onClick={() => openEdit("new")}><Plus className="h-4 w-4" />Add camera</GlassButton>} />
      <ErrorNote error={q.error} />
      {q.isLoading && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}</div>}
      {q.data && q.data.length === 0 && <GlassCard><EmptyState icon={<CamIcon className="h-5 w-5" />} title="No cameras configured" description={admin ? "Add an RTSP stream, webcam or video file." : "An administrator has not added any cameras."} /></GlassCard>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(q.data ?? []).map((c, i) => (
          <GlassCard key={c.id} delay={i * 0.04}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0"><h3 className="truncate font-semibold">{c.name}</h3><p className="text-xs uppercase text-muted">{c.type}</p></div>
              <StatusBadge color={STATUS_COLOR[c.status]} label={c.status} pulse={c.status === "live"} />
            </div>
            <p className="mt-2 break-all font-mono text-xs text-muted">{c.source_masked}</p>
            {c.description && <p className="mt-1 text-sm">{c.description}</p>}
            {c.last_error && <p role="status" className="mt-2 text-xs text-danger">Reconnect state: {c.last_error}</p>}
            <div className="mt-3 flex items-center justify-between">
              <StatusBadge color={c.enabled ? "#22c55e" : "#9ca3af"} label={c.enabled ? "enabled" : "disabled"} />
              {admin && <div className="flex gap-1">
                <button type="button" aria-label={`Edit ${c.name}`} onClick={() => openEdit(c)} className="rounded-lg p-2 text-muted hover:bg-[var(--glass-strong)] hover:text-fg"><Pencil className="h-4 w-4" /></button>
                <button type="button" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)} className="rounded-lg p-2 text-danger hover:bg-[var(--glass-strong)]"><Trash2 className="h-4 w-4" /></button>
              </div>}
            </div>
          </GlassCard>
        ))}
      </div>

      <GlassModal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add camera" : "Edit camera"}>
        <form onSubmit={submit} className="space-y-3" noValidate>
          <Field label="Name" {...form.register("name")} error={form.formState.errors.name?.message} />
          <div><label className="label" htmlFor="cam-type">Type</label><select id="cam-type" className="field" {...form.register("type")}><option value="rtsp">RTSP stream</option><option value="http">HTTP stream</option><option value="webcam">Server webcam</option><option value="file">Video file</option></select></div>
          <Field label={editing === "new" ? "Source (URL, device index or file path)" : "Source (leave empty to keep the current one)"} autoComplete="off" {...form.register("source")} error={form.formState.errors.source?.message} />
          <Field label="Description" {...form.register("description")} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" {...form.register("enabled")} />Enabled</label>
          <div className="flex justify-end gap-2"><GlassButton variant="ghost" onClick={() => setEditing(null)}>Cancel</GlassButton><GlassButton type="submit" loading={save.isPending}>Save</GlassButton></div>
        </form>
      </GlassModal>

      <GlassModal open={deleting !== null} onClose={() => setDeleting(null)} title="Delete camera"
        footer={<><GlassButton variant="ghost" onClick={() => setDeleting(null)}>Cancel</GlassButton><GlassButton variant="danger" loading={del.isPending} onClick={() => deleting && del.mutate(deleting)}>Delete</GlassButton></>}>
        <p className="text-sm">Remove camera <strong>{deleting?.name}</strong>?</p>
      </GlassModal>
    </div>
  );
}
