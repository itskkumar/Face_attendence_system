"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Pencil, ScanFace, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ChangeEvent } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Page, Student } from "@/lib/types";
import { toQuery } from "@/lib/utils";
import { PageHeader } from "@/components/features/shared";
import { Field, GlassButton, SearchInput, StatusBadge } from "@/components/ui/glass";
import { GlassModal } from "@/components/ui/modal";
import { GlassTable } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";

const PAGE_SIZE = 25;
type Edit = Pick<Student, "roll_number" | "name" | "email" | "phone" | "department" | "batch" | "expected_time">;

export default function StudentsPage() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const qc = useQueryClient();
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Edit | null>(null);
  const [deleting, setDeleting] = useState<Student | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [importResult, setImportResult] = useState<{ updated: number; skipped: number; errors: string[] } | null>(null);

  const q = useQuery({ queryKey: ["students", search, page], queryFn: () => api<Page<Student>>(`/students${toQuery({ q: search, page, page_size: PAGE_SIZE })}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["students"] });

  const save = useMutation({
    mutationFn: (e: Edit) => api<Student>(`/students/${encodeURIComponent(e.roll_number)}/profile`, { method: "POST", body: { name: e.name, email: e.email, phone: e.phone, department: e.department, batch: e.batch, expected_time: e.expected_time } }),
    onSuccess: () => { toast({ title: "Student updated", variant: "success" }); setEditing(null); void refresh(); },
    onError: (e) => toast({ title: "Could not save", description: errorMessage(e), variant: "error" }),
  });
  const del = useMutation({
    mutationFn: (s: Student) => api(`/students/${encodeURIComponent(s.roll_number)}`, { method: "DELETE" }),
    onSuccess: () => { toast({ title: "Student deleted", variant: "success" }); setDeleting(null); void refresh(); },
    onError: (e) => toast({ title: "Could not delete", description: errorMessage(e), variant: "error" }),
  });
  const imp = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api<{ updated: number; skipped: number; errors: string[] }>("/students/import", { method: "POST", form: fd }); },
    onSuccess: (r) => { setImportResult(r); void refresh(); },
    onError: (e) => toast({ title: "Import failed", description: errorMessage(e), variant: "error" }),
  });

  const columns = useMemo<ColumnDef<Student, unknown>[]>(() => [
    { accessorKey: "roll_number", header: "Roll no." },
    { accessorKey: "name", header: "Name" },
    { accessorKey: "department", header: "Department" },
    { accessorKey: "batch", header: "Batch" },
    { accessorKey: "expected_time", header: "Expected" },
    { accessorKey: "template_count", header: "Face templates", cell: ({ getValue }) => (getValue() as number) > 0 ? <StatusBadge color="#22c55e" label={`${getValue() as number} enrolled`} /> : <StatusBadge color="#f97316" label="not enrolled" /> },
    ...(admin ? [{
      id: "actions", header: "", enableSorting: false,
      cell: ({ row }: { row: { original: Student } }) => {
        const s = row.original;
        return (
          <div className="flex justify-end gap-1">
            <Link aria-label={`Re-enroll ${s.name}`} title="Re-enroll face" href={`/admin/enrollment?roll=${encodeURIComponent(s.roll_number)}&name=${encodeURIComponent(s.name)}`} className="rounded-lg p-2 text-muted hover:bg-[var(--glass-strong)] hover:text-fg"><ScanFace className="h-4 w-4" /></Link>
            <button type="button" aria-label={`Edit ${s.name}`} onClick={() => setEditing({ roll_number: s.roll_number, name: s.name, email: s.email, phone: s.phone, department: s.department, batch: s.batch, expected_time: s.expected_time })} className="rounded-lg p-2 text-muted hover:bg-[var(--glass-strong)] hover:text-fg"><Pencil className="h-4 w-4" /></button>
            <button type="button" aria-label={`Delete ${s.name}`} onClick={() => setDeleting(s)} className="rounded-lg p-2 text-danger hover:bg-[var(--glass-strong)]"><Trash2 className="h-4 w-4" /></button>
          </div>
        );
      },
    } as ColumnDef<Student, unknown>] : []),
  ], [admin]);

  const setField = (k: keyof Edit) => (e: ChangeEvent<HTMLInputElement>) => setEditing((p) => (p ? { ...p, [k]: e.target.value } : p));

  return (
    <div className="space-y-5">
      <PageHeader title="Students" description={admin ? "Manage enrolled students" : "Read-only student list"}
        actions={<>
          <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder="Name or roll number" className="w-60" label="Search students" />
          {admin && <GlassButton variant="ghost" onClick={() => { setImportResult(null); setFile(null); setImportOpen(true); }}><Upload className="h-4 w-4" />Import CSV</GlassButton>}
          {admin && <Link href="/admin/enrollment" className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white shadow-glow"><ScanFace className="h-4 w-4" />Enroll student</Link>}
        </>} />
      <GlassTable data={q.data?.items ?? []} columns={columns} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null}
        pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: setPage }} emptyTitle="No students found" emptyDescription={search ? "Try a different search." : "Enroll a student or import a CSV to get started."} caption="Students" />

      <GlassModal open={editing !== null} onClose={() => setEditing(null)} title={`Edit ${editing?.roll_number ?? ""}`}
        footer={<><GlassButton variant="ghost" onClick={() => setEditing(null)}>Cancel</GlassButton><GlassButton loading={save.isPending} onClick={() => editing && save.mutate(editing)}>Save</GlassButton></>}>
        {editing && <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" value={editing.name} onChange={setField("name")} className="sm:col-span-2" />
          <Field label="Email" type="email" value={editing.email} onChange={setField("email")} />
          <Field label="Phone" value={editing.phone} onChange={setField("phone")} />
          <Field label="Department" value={editing.department} onChange={setField("department")} />
          <Field label="Batch" value={editing.batch} onChange={setField("batch")} />
          <Field label="Expected time (HH:MM)" value={editing.expected_time} onChange={setField("expected_time")} />
        </div>}
      </GlassModal>

      <GlassModal open={deleting !== null} onClose={() => setDeleting(null)} title="Delete student"
        footer={<><GlassButton variant="ghost" onClick={() => setDeleting(null)}>Cancel</GlassButton><GlassButton variant="danger" loading={del.isPending} onClick={() => deleting && del.mutate(deleting)}>Delete</GlassButton></>}>
        <p className="text-sm">Delete <strong>{deleting?.name}</strong> ({deleting?.roll_number}) and their face templates? The action is audit-logged and cannot be undone.</p>
      </GlassModal>

      <GlassModal open={importOpen} onClose={() => setImportOpen(false)} title="Import students from CSV"
        footer={<><GlassButton variant="ghost" onClick={() => setImportOpen(false)}>Close</GlassButton><GlassButton disabled={!file} loading={imp.isPending} onClick={() => file && imp.mutate(file)}>Import</GlassButton></>}>
        <p className="mb-3 text-sm text-muted">Columns: <code>roll_number, name</code> and optionally <code>email, phone, department, batch, expected_time</code>. Imported students have no face template until enrolled.</p>
        <label className="label" htmlFor="csv-file">CSV file</label>
        <input id="csv-file" type="file" accept=".csv,text/csv" className="field" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        {importResult && (
          <div className="mt-4 space-y-1 text-sm" role="status">
            <p>Updated: <strong>{importResult.updated}</strong> | Skipped: <strong>{importResult.skipped}</strong></p>
            {importResult.errors.length > 0 && <ul className="max-h-40 list-disc overflow-y-auto pl-5 text-danger">{importResult.errors.map((er, i) => <li key={i}>{er}</li>)}</ul>}
          </div>
        )}
      </GlassModal>
    </div>
  );
}
