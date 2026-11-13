"use client";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { homeFor } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LiveFeedProvider } from "@/lib/live-feed";
import { canAccess } from "@/lib/nav";
import { Skeleton } from "@/components/ui/glass";
import { ForcedPasswordChange } from "@/components/features/password-change";
import { GlassSidebar } from "./sidebar";
import { GlassTopbar } from "./topbar";

/**
 * Client-side route guard + chrome. This only improves UX: the API enforces roles on every request.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, mustReset } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const allowed = user ? canAccess(user.role, pathname) : false;

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (!allowed) router.replace(homeFor(user.role));
  }, [loading, user, allowed, router]);

  if (loading || !user || !allowed) {
    return <div className="p-8" aria-busy="true"><Skeleton className="mb-4 h-10 w-64" /><Skeleton className="h-64 w-full" /></div>;
  }
  const staff = user.role !== "student";
  return (
    <LiveFeedProvider enabled={staff}>
      <div className="flex min-h-screen">
        <GlassSidebar role={user.role} collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} mobileOpen={mobile} onCloseMobile={() => setMobile(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <GlassTopbar onOpenMenu={() => setMobile(true)} />
          <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 md:p-6">{children}</main>
        </div>
      </div>
      <ForcedPasswordChange open={mustReset} />
    </LiveFeedProvider>
  );
}
