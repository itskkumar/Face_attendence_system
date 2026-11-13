"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Field, GlassButton } from "@/components/ui/glass";
import { GlassModal } from "@/components/ui/modal";

const schema = z.object({
  current_password: z.string().min(1, "Enter your current password"),
  new_password: z.string().min(10, "At least 10 characters"),
  confirm: z.string(),
}).refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });
type Form = z.infer<typeof schema>;

/** Blocking dialog shown when the account must change its (temporary) password. */
export function ForcedPasswordChange({ open }: { open: boolean }) {
  const { refresh } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Form>({ resolver: zodResolver(schema) });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      await api("/auth/change-password", { method: "POST", body: { current_password: v.current_password, new_password: v.new_password } });
      await refresh();
    } catch (e) { setError(errorMessage(e)); }
  });
  return (
    <GlassModal open={open} onClose={() => undefined} dismissible={false} title="Choose a new password">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-muted">Your account uses a temporary password. Set a new one to continue.</p>
        <Field label="Current (temporary) password" type="password" autoComplete="current-password" {...register("current_password")} error={errors.current_password?.message} />
        <Field label="New password" type="password" autoComplete="new-password" {...register("new_password")} error={errors.new_password?.message} />
        <Field label="Confirm new password" type="password" autoComplete="new-password" {...register("confirm")} error={errors.confirm?.message} />
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <GlassButton type="submit" loading={isSubmitting} className="w-full">Save password</GlassButton>
      </form>
    </GlassModal>
  );
}
