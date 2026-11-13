"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import { Field, GlassButton } from "@/components/ui/glass";

const schema = z.object({
  username: z.string().trim().min(1, "Enter your username"),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function LoginForm({ onSuccess }: { onSuccess: (user: User) => void }) {
  const { login } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<Values>({ resolver: zodResolver(schema) });
  const submit = handleSubmit(async (v) => {
    setError(null);
    try {
      const s = await login(v.username, v.password);
      onSuccess(s.user);
    } catch (e) {
      setError(errorMessage(e));
    }
  });
  return (
    <form onSubmit={submit} className="space-y-4" noValidate aria-label="Sign in">
      <Field label="Username" autoComplete="username" {...register("username")} error={errors.username?.message} />
      <Field label="Password" type="password" autoComplete="current-password" {...register("password")} error={errors.password?.message} />
      {error && <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      <GlassButton type="submit" loading={isSubmitting} className="w-full">Sign in</GlassButton>
    </form>
  );
}
