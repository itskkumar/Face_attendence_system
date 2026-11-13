"use client";
import { motion } from "framer-motion";
import { ChevronsLeft, ChevronsRight, ScanFace, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { navForRole } from "@/lib/nav";
import type { Role } from "@/lib/types";
import { cn } from "@/lib/utils";

export function GlassSidebar({ role, collapsed, onToggle, mobileOpen, onCloseMobile }: {
  role: Role; collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onCloseMobile: () => void;
}) {
  const pathname = usePathname();
  const items = navForRole(role);
  const sections = Array.from(new Set(items.map((i) => i.section)));

  const body = (isCollapsed: boolean, mobile: boolean) => (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="rounded-xl bg-primary/20 p-2 text-primary"><ScanFace className="h-5 w-5" /></div>
        {!isCollapsed && <span className="font-semibold">FaceAttend</span>}
        {mobile && <button type="button" aria-label="Close menu" onClick={onCloseMobile} className="ml-auto rounded-lg p-1 text-muted"><X className="h-4 w-4" /></button>}
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 pb-4">
        {sections.map((sec) => (
          <div key={sec} className="mb-3">
            {!isCollapsed && <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">{sec}</p>}
            {items.filter((i) => i.section === sec).map((item) => {
              const active = pathname === item.href || pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <Link key={item.href} href={item.href} onClick={onCloseMobile} title={isCollapsed ? item.label : undefined}
                  aria-current={active ? "page" : undefined}
                  className={cn("relative mb-0.5 flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition", active ? "text-fg" : "text-muted hover:text-fg hover:bg-[var(--glass-strong)]")}>
                  {active && <motion.span layoutId={mobile ? "nav-active-m" : "nav-active"} className="absolute inset-0 rounded-xl border border-primary/40 bg-primary/15" transition={{ type: "spring", stiffness: 420, damping: 36 }} />}
                  <Icon className="relative h-4 w-4 shrink-0" aria-hidden />
                  {!isCollapsed && <span className="relative truncate">{item.label}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </div>
  );

  return (
    <>
      <motion.aside className="glass sticky top-0 hidden h-screen shrink-0 overflow-hidden border-y-0 border-l-0 md:block"
        animate={{ width: collapsed ? 72 : 256 }} initial={false} transition={{ type: "spring", stiffness: 300, damping: 32 }}>
        {body(collapsed, false)}
        <button type="button" onClick={onToggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute bottom-3 right-3 rounded-lg p-1.5 text-muted hover:bg-[var(--glass-strong)] hover:text-fg">
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
        </button>
      </motion.aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/55" onClick={onCloseMobile} aria-hidden />
          <motion.aside initial={{ x: -280 }} animate={{ x: 0 }} transition={{ type: "spring", stiffness: 320, damping: 34 }} className="glass glass-strong absolute inset-y-0 left-0 w-64">
            {body(false, true)}
          </motion.aside>
        </div>
      )}
    </>
  );
}
