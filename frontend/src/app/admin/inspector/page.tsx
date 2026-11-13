"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Inspector } from "@/lib/types";
import { ErrorNote, KeyValue, PadChip, PageHeader, Section } from "@/components/features/shared";
import { Skeleton, StatusBadge } from "@/components/ui/glass";

export default function InspectorPage() {
  const q = useQuery({ queryKey: ["inspector"], queryFn: () => api<Inspector>("/inspector") });
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Math Inspector" description="Read-only diagnostics. Embeddings and templates are never sent to the browser." />
      <ErrorNote error={q.error} />
      {q.isLoading && <Skeleton className="h-64 w-full" />}
      {d && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Section title="Gallery"><KeyValue rows={[["Students", d.gallery.students], ["Templates", d.gallery.templates], ["Index version", String(d.gallery.version)], ["Backend", d.gallery.backend]]} /></Section>
          <Section title="Anti-spoofing (PAD)">
            <div className="mb-3"><PadChip health={d.pad} /></div>
            <KeyValue rows={[["State", d.pad.state], ["Model", d.pad.model_id || "none"], ["Provider", d.pad.provider || "-"], ["Reason", d.pad.reason || "-"]]} />
          </Section>
          <Section title="Model files"><ul className="space-y-2 text-sm">{d.models.map((m) => (<li key={m.name} className="flex items-center justify-between gap-2"><span className="break-all">{m.name}</span><StatusBadge color={m.present ? "#22c55e" : "#ef4444"} label={m.present ? "present" : "missing"} /></li>))}</ul></Section>
          <Section title="Active settings"><KeyValue rows={Object.entries(d.settings).map(([k, v]) => [k, String(v)] as [string, string])} /></Section>
        </div>
      )}
    </div>
  );
}
