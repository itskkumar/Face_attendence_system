"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AuthState, User } from "@/lib/types";
import { Field, GlassButton } from "@/components/ui/glass";

const schema = z.object({
  setup_token: z.string().min(1, "Paste the setup token from the API server log"),
  username: z.string().trim().min(3, "At least 3 characters"),
  password: z.string().min(10, "At least 10 characters"),
  confirm: z.string(),
}).refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Values = z.infer<typeof schema>;

export function SetupForm({ onSuccess }: { onSuccess: (user: User) => void }) {
  const { applyAuth } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      const s = await api<AuthState>("/auth/setup", { method: "POST", body: { setup_token: v.setup_token, username: v.username, password: v.password } });
      applyAuth(s);
      onSuccess(s.user);
    } catch (e) { setError(errorMessage(e)); }
  });
  return (
    <form onSubmit={submit} className="space-y-4" noValidate aria-label="First-run setup">
      <p className="text-sm text-muted">No administrator exists yet. Create the first admin. The one-time setup token is printed in the API server log when it starts.</p>
      <Field label="Setup token" autoComplete="off" {...register("setup_token")} error={errors.setup_token?.message} />
      <Field label="Admin username" autoComplete="username" {...register("username")} error={errors.username?.message} />
      <Field label="Password" type="password" autoComplete="new-password" {...register("password")} error={errors.password?.message} />
      <Field label="Confirm password" type="password" autoComplete="new-password" {...register("confirm")} error={errors.confirm?.message} />
      {error && <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      <GlassButton type="submit" loading={isSubmitting} className="w-full">Create administrator</GlassButton>
    </form>
  );
}
