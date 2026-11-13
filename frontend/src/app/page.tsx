"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Skeleton } from "@/components/ui/glass";

export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading) router.replace(user ? homeFor(user.role) : "/login");
  }, [loading, user, router]);
  return <div className="p-8"><Skeleton className="h-10 w-64" /></div>;
}
