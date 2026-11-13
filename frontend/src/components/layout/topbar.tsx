"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, ChevronRight, LogOut, Menu, UserCircle } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useLiveFeed } from "@/lib/live-feed";
import { navItemFor } from "@/lib/nav";
import { EVENT_LABELS, eventColor } from "@/lib/status";
import { SearchInput, StatusBadge } from "@/components/ui/glass";
import { ThemeToggle } from "./theme";

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => { setNow(new Date()); const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  return <time className="hidden tabular-nums text-sm text-muted lg:block">{now ? now.toLocaleTimeString() : ""}</time>;
}

export function GlassTopbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const { events, status, socket } = useLiveFeed();
  const [q, setQ] = useState("");
  const [menu, setMenu] = useState<"profile" | "bell" | null>(null);
  const [seen, setSeen] = useState(0);
  const wrap = useRef<HTMLDivElement | null>(null);
  const item = navItemFor(pathname);
  const staff = user?.role === "admin" || user?.role === "operator";
  const alerts = events.filter((e) => ["liveness.failed", "identity.unknown", "review.required"].includes(e.type));

  useEffect(() => {
    const close = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setMenu(null); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const crumbs = pathname.split("/").filter(Boolean);
  const unseen = Math.max(0, alerts.length - seen);

  return (
    <header className="glass sticky top-0 z-30 flex items-center gap-3 border-x-0 border-t-0 px-4 py-2.5">
      <button type="button" aria-label="Open menu" onClick={onOpenMenu} className="rounded-xl p-2 text-muted hover:text-fg md:hidden"><Menu className="h-5 w-5" /></button>
      <div className="min-w-0">
        <h1 className="truncate text-base font-semibold">{item?.label ?? "FaceAttend"}</h1>
        <nav aria-label="Breadcrumb" className="hidden items-center gap-1 text-xs text-muted sm:flex">
          {crumbs.map((c, i) => (<span key={i} className="flex items-center gap-1">{i > 0 && <ChevronRight className="h-3 w-3" />}<span className="capitalize">{c}</span></span>))}
        </nav>
      </div>
      <div className="ml-auto flex items-center gap-2" ref={wrap}>
        {staff && (
          <form className="hidden w-56 md:block" onSubmit={(e) => { e.preventDefault(); if (q.trim()) router.push(`/admin/search?name=${encodeURIComponent(q.trim())}`); }} role="search">
            <SearchInput value={q} onChange={setQ} placeholder="Search attendance by name" label="Search attendance by name" />
          </form>
        )}
        {staff && (
          <div className="hidden items-center gap-2 lg:flex">
            <StatusBadge color={status?.running ? "#22c55e" : "#9ca3af"} label={status?.running ? "Camera live" : "Camera idle"} pulse={Boolean(status?.running)} />
            <StatusBadge color={socket === "open" ? "#22c55e" : socket === "failed" ? "#ef4444" : "#eab308"} label={socket === "open" ? "System online" : socket === "failed" ? "Feed denied" : "Connecting"} />
          </div>
        )}
        <Clock />
        <ThemeToggle />
        {staff && (
          <div className="relative">
            <button type="button" aria-label={`Notifications${unseen ? `, ${unseen} new` : ""}`} onClick={() => { setMenu(menu === "bell" ? null : "bell"); setSeen(alerts.length); }}
              className="relative rounded-xl p-2 text-muted hover:bg-[var(--glass-strong)] hover:text-fg">
              <Bell className="h-4 w-4" />
              {unseen > 0 && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-danger" />}
            </button>
            <AnimatePresence>
              {menu === "bell" && (
                <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="glass glass-strong absolute right-0 mt-2 w-80 rounded-xl2 p-2">
                  <p className="px-2 py-1 text-xs font-semibold text-muted">Security alerts</p>
                  {alerts.length === 0 && <p className="px-2 py-4 text-center text-sm text-muted">No alerts this session</p>}
                  <ul className="max-h-72 overflow-y-auto">
                    {alerts.slice(0, 12).map((e) => (
                      <li key={e.event_id} className="flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm">
                        <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: eventColor(e.type) }} />
                        <span><span className="font-medium">{EVENT_LABELS[e.type] ?? e.type}</span>{e.student ? ` - ${e.student.name}` : ""}<br /><span className="text-xs text-muted">{new Date(e.ts).toLocaleTimeString()} | {e.camera_id} | track {e.track_id}</span></span>
                      </li>
                    ))}
                  </ul>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        <div className="relative">
          <button type="button" aria-label="Profile menu" onClick={() => setMenu(menu === "profile" ? null : "profile")} className="flex items-center gap-2 rounded-xl px-2 py-1.5 hover:bg-[var(--glass-strong)]">
            <UserCircle className="h-5 w-5 text-primary" /><span className="hidden text-sm sm:inline">{user?.username}</span>
          </button>
          <AnimatePresence>
            {menu === "profile" && user && (
              <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="glass glass-strong absolute right-0 mt-2 w-56 rounded-xl2 p-2">
                <div className="px-3 py-2"><p className="text-sm font-medium">{user.username}</p><p className="text-xs capitalize text-muted">{user.role}</p></div>
                {user.role === "student" && <Link href="/student/profile" onClick={() => setMenu(null)} className="block rounded-lg px-3 py-2 text-sm hover:bg-[var(--glass-strong)]">My profile</Link>}
                <button type="button" onClick={async () => { await logout(); router.replace("/login"); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-danger hover:bg-[var(--glass-strong)]"><LogOut className="h-4 w-4" />Sign out</button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}
