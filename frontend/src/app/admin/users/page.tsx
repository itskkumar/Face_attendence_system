"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Copy, KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Role, UserRow } from "@/lib/types";
import { PageHeader } from "@/components/features/shared";
import { Field, GlassButton, SearchInput, StatusBadge } from "@/components/ui/glass";
import { GlassModal } from "@/components/ui/modal";
import { GlassTable } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";

const createSchema = z.object({
  username: z.string().trim().min(3, "At least 3 characters"),
  role: z.enum(["admin", "operator", "student"]),
  roll_number: z.string().trim().optional(),
  password: z.string().min(10, "At least 10 characters"),
}).refine((v) => v.role !== "student" || Boolean(v.roll_number), { path: ["roll_number"], message: "Required for students" });
type CreateValues = z.infer<typeof createSchema>;

export default function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [filter, setFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [secret, setSecret] = useState<{ title: string; rows: { username: string; temporary_password: string }[] } | null>(null);
  const [deleting, setDeleting] = useState<UserRow | null>(null);

  const q = useQuery({ queryKey: ["users"], queryFn: () => api<UserRow[]>("/users") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });
  const onError = (title: string) => (e: unknown) => toast({ title, description: errorMessage(e), variant: "error" });

  const form = useForm<CreateValues>({ resolver: zodResolver(createSchema), defaultValues: { role: "operator" } });
  const role = form.watch("role");

  const create = useMutation({
    mutationFn: (v: CreateValues) => api<UserRow>("/users", { method: "POST", body: { ...v, roll_number: v.role === "student" ? v.roll_number : undefined } }),
    onSuccess: () => { toast({ title: "User created", variant: "success" }); setCreateOpen(false); form.reset({ role: "operator" }); void refresh(); },
    onError: onError("Could not create user"),
  });
  const patch = useMutation({
    mutationFn: ({ username, body }: { username: string; body: Partial<Pick<UserRow, "role" | "disabled">> }) => api<UserRow>(`/users/${encodeURIComponent(username)}`, { method: "PATCH", body }),
    onSuccess: () => void refresh(), onError: onError("Could not update user"),
  });
  const temp = useMutation({
    mutationFn: (username: string) => api<{ temporary_password: string }>(`/users/${encodeURIComponent(username)}/temporary-password`, { method: "POST" }).then((r) => ({ username, ...r })),
    onSuccess: (r) => { setSecret({ title: "Temporary password", rows: [r] }); void refresh(); }, onError: onError("Could not set temporary password"),
  });
  const del = useMutation({
    mutationFn: (u: UserRow) => api(`/users/${encodeURIComponent(u.username)}`, { method: "DELETE" }),
    onSuccess: () => { toast({ title: "User deleted", variant: "success" }); setDeleting(null); void refresh(); }, onError: onError("Could not delete user"),
  });
  const bulk = useMutation({
    mutationFn: (rolls: string[]) => api<{ created: { username: string; temporary_password: string }[] }>("/users/student-accounts", { method: "POST", body: { roll_numbers: rolls } }),
    onSuccess: (r) => { setBulkOpen(false); setSecret({ title: `${r.created.length} student account(s) created`, rows: r.created }); void refresh(); }, onError: onError("Could not create student accounts"),
  });

  const columns = useMemo<ColumnDef<UserRow, unknown>[]>(() => [
    { accessorKey: "username", header: "Username" },
    { accessorKey: "role", header: "Role", cell: ({ row }) => {
      const u = row.original;
      return (
        <select aria-label={`Role for ${u.username}`} className="field w-32 py-1" value={u.role} disabled={u.username === me?.username}
          onChange={(e) => patch.mutate({ username: u.username, body: { role: e.target.value as Role } })}>
          <option value="admin">admin</option><option value="operator">operator</option><option value="student">student</option>
        </select>);
    } },
    { accessorKey: "roll_number", header: "Roll no.", cell: ({ getValue }) => (getValue() as string | null) ?? "-" },
    { id: "state", header: "State", enableSorting: false, cell: ({ row }) => {
      const u = row.original;
      return u.disabled ? <StatusBadge color="#9ca3af" label="disabled" /> : !u.has_password ? <StatusBadge color="#f97316" label="no password set" /> : u.must_reset ? <StatusBadge color="#eab308" label="must reset" /> : <StatusBadge color="#22c55e" label="active" />;
    } },
    { accessorKey: "created_at", header: "Created" },
    { id: "actions", header: "", enableSorting: false, cell: ({ row }) => {
      const u = row.original; const self = u.username === me?.username;
      return (
        <div className="flex justify-end gap-1">
          <button type="button" aria-label={`Set temporary password for ${u.username}`} title="Set temporary password" onClick={() => temp.mutate(u.username)} className="rounded-lg p-2 text-muted hover:bg-[var(--glass-strong)] hover:text-fg"><KeyRound className="h-4 w-4" /></button>
          <button type="button" disabled={self} onClick={() => patch.mutate({ username: u.username, body: { disabled: !u.disabled } })} className="rounded-lg px-2 text-xs text-muted hover:bg-[var(--glass-strong)] hover:text-fg disabled:opacity-40">{u.disabled ? "Enable" : "Disable"}</button>
          <button type="button" disabled={self} aria-label={`Delete ${u.username}`} onClick={() => setDeleting(u)} className="rounded-lg p-2 text-danger hover:bg-[var(--glass-strong)] disabled:opacity-40"><Trash2 className="h-4 w-4" /></button>
        </div>);
    } },
  ], [me?.username, patch, temp]);

  const rolls = bulkText.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);

  return (
    <div className="space-y-5">
      <PageHeader title="Users" description="Accounts and roles. Roles are enforced by the server."
        actions={<>
          <SearchInput value={filter} onChange={setFilter} placeholder="Filter users" className="w-52" label="Filter users" />
          <GlassButton variant="ghost" onClick={() => { setBulkText(""); setBulkOpen(true); }}><Users className="h-4 w-4" />Student accounts</GlassButton>
          <GlassButton onClick={() => setCreateOpen(true)}><UserPlus className="h-4 w-4" />New user</GlassButton>
        </>} />
      <GlassTable data={q.data ?? []} columns={columns} loading={q.isLoading} error={q.error ? errorMessage(q.error) : null} globalFilter={filter} emptyTitle="No users" caption="User accounts" />

      <GlassModal open={createOpen} onClose={() => setCreateOpen(false)} title="New user">
        <form onSubmit={form.handleSubmit((v) => create.mutate(v))} className="space-y-3" noValidate>
          <Field label="Username" {...form.register("username")} error={form.formState.errors.username?.message} />
          <div><label className="label" htmlFor="role-sel">Role</label><select id="role-sel" className="field" {...form.register("role")}><option value="admin">admin</option><option value="operator">operator</option><option value="student">student</option></select></div>
          {role === "student" && <Field label="Roll number" {...form.register("roll_number")} error={form.formState.errors.roll_number?.message} />}
          <Field label="Initial password" type="password" autoComplete="new-password" {...form.register("password")} error={form.formState.errors.password?.message} />
          <p className="text-xs text-muted">The user must choose a new password at first sign-in.</p>
          <div className="flex justify-end gap-2"><GlassButton variant="ghost" onClick={() => setCreateOpen(false)}>Cancel</GlassButton><GlassButton type="submit" loading={create.isPending}>Create</GlassButton></div>
        </form>
      </GlassModal>

      <GlassModal open={bulkOpen} onClose={() => setBulkOpen(false)} title="Create student accounts"
        footer={<><GlassButton variant="ghost" onClick={() => setBulkOpen(false)}>Cancel</GlassButton><GlassButton disabled={rolls.length === 0} loading={bulk.isPending} onClick={() => bulk.mutate(rolls)}>Create {rolls.length || ""} account(s)</GlassButton></>}>
        <label className="label" htmlFor="bulk-rolls">Roll numbers (separated by spaces, commas or new lines)</label>
        <textarea id="bulk-rolls" rows={6} className="field" value={bulkText} onChange={(e) => setBulkText(e.target.value)} />
        <p className="mt-2 text-xs text-muted">Each student gets a random one-time password, shown once, and must change it at first sign-in.</p>
      </GlassModal>

      <GlassModal open={secret !== null} onClose={() => setSecret(null)} title={secret?.title ?? ""}
        footer={<>
          <GlassButton variant="ghost" onClick={() => { if (secret) void navigator.clipboard?.writeText(secret.rows.map((r) => `${r.username}\t${r.temporary_password}`).join("\n")).then(() => toast({ title: "Copied", variant: "success" }), () => toast({ title: "Copy failed", variant: "error" })); }}><Copy className="h-4 w-4" />Copy all</GlassButton>
          <GlassButton onClick={() => setSecret(null)}>Done</GlassButton></>}>
        <p className="mb-3 text-sm text-warn">These passwords are shown once. Share them securely.</p>
        <ul className="max-h-64 space-y-1 overflow-y-auto font-mono text-sm">{secret?.rows.map((r) => (<li key={r.username} className="flex justify-between gap-3 rounded-lg bg-[var(--glass-strong)] px-3 py-1.5"><span>{r.username}</span><span>{r.temporary_password}</span></li>))}</ul>
      </GlassModal>

      <GlassModal open={deleting !== null} onClose={() => setDeleting(null)} title="Delete user"
        footer={<><GlassButton variant="ghost" onClick={() => setDeleting(null)}>Cancel</GlassButton><GlassButton variant="danger" loading={del.isPending} onClick={() => deleting && del.mutate(deleting)}>Delete</GlassButton></>}>
        <p className="text-sm">Delete the account <strong>{deleting?.username}</strong>? This does not delete a student's attendance records.</p>
      </GlassModal>
    </div>
  );
}
