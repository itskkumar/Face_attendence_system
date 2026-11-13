"use client";
import { useQuery } from "@tanstack/react-query";
import { ScanFace } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { api, homeFor } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LoginForm } from "@/components/features/login-form";
import { SetupForm } from "@/components/features/setup-form";
import { GlassCard, Skeleton } from "@/components/ui/glass";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const status = useQuery({ queryKey: ["auth-status"], queryFn: () => api<{ setup_required: boolean }>("/auth/status") });

  useEffect(() => { if (!loading && user) router.replace(homeFor(user.role)); }, [loading, user, router]);

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -left-24 top-10 h-96 w-96 animate-float rounded-full bg-primary/30 blur-3xl" />
        <div className="absolute -right-24 bottom-0 h-[28rem] w-[28rem] animate-float rounded-full bg-accent/25 blur-3xl [animation-delay:-5s]" />
        <div className="absolute left-1/3 top-2/3 h-72 w-72 animate-float rounded-full bg-purple/25 blur-3xl [animation-delay:-9s]" />
      </div>
      <GlassCard className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-3">
          <div className="rounded-2xl bg-primary/20 p-3 text-primary"><ScanFace className="h-6 w-6" /></div>
          <div><h1 className="text-xl font-semibold">FaceAttend</h1><p className="text-sm text-muted">{status.data?.setup_required ? "First-run setup" : "Sign in to continue"}</p></div>
        </div>
        {status.isLoading && <Skeleton className="h-40 w-full" />}
        {status.isError && <p role="alert" className="text-sm text-danger">Cannot reach the server: {(status.error as Error).message}</p>}
        {status.data && (status.data.setup_required
          ? <SetupForm onSuccess={(u) => router.replace(homeFor(u.role))} />
          : <LoginForm onSuccess={(u) => router.replace(homeFor(u.role))} />)}
      </GlassCard>
    </div>
  );
}
