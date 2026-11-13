import { BarChart3, Camera, Gauge, GraduationCap, LayoutDashboard, ScanFace, Search, ShieldAlert, Telescope, UserCircle, UserCog, UserPlus, CalendarCheck, type LucideIcon } from "lucide-react";
import type { Role } from "./types";

export interface NavItem { href: string; label: string; icon: LucideIcon; roles: Role[]; section: string }

export const NAV: NavItem[] = [
  { href: "/admin/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: ["admin", "operator"], section: "Overview" },
  { href: "/security/monitor", label: "Security Monitor", icon: ShieldAlert, roles: ["admin", "operator"], section: "Overview" },
  { href: "/admin/live", label: "Live Feed", icon: ScanFace, roles: ["admin", "operator"], section: "Gate" },
  { href: "/admin/cameras", label: "Cameras", icon: Camera, roles: ["admin", "operator"], section: "Gate" },
  { href: "/admin/enrollment", label: "Enrollment", icon: UserPlus, roles: ["admin"], section: "People" },
  { href: "/admin/students", label: "Students", icon: GraduationCap, roles: ["admin", "operator"], section: "People" },
  { href: "/admin/users", label: "Users", icon: UserCog, roles: ["admin"], section: "People" },
  { href: "/admin/search", label: "Search", icon: Search, roles: ["admin", "operator"], section: "Records" },
  { href: "/admin/analytics", label: "Analytics", icon: BarChart3, roles: ["admin", "operator"], section: "Records" },
  { href: "/admin/system", label: "System Health", icon: Gauge, roles: ["admin", "operator"], section: "System" },
  { href: "/admin/inspector", label: "Math Inspector", icon: Telescope, roles: ["admin"], section: "System" },
  { href: "/student/dashboard", label: "My Dashboard", icon: LayoutDashboard, roles: ["student"], section: "Student" },
  { href: "/student/attendance", label: "My Attendance", icon: CalendarCheck, roles: ["student"], section: "Student" },
  { href: "/student/profile", label: "My Profile", icon: UserCircle, roles: ["student"], section: "Student" },
];

export const navForRole = (role: Role): NavItem[] => NAV.filter((n) => n.roles.includes(role));

export function navItemFor(pathname: string): NavItem | undefined {
  return NAV.find((n) => pathname === n.href || pathname.startsWith(n.href + "/"));
}

/** Client-side convenience only; the server enforces every route. */
export function canAccess(role: Role, pathname: string): boolean {
  const item = navItemFor(pathname);
  return item ? item.roles.includes(role) : false;
}
