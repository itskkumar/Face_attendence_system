import { describe, expect, it } from "vitest";
import { homeFor } from "@/lib/api";
import { canAccess, navForRole } from "@/lib/nav";

describe("role based navigation", () => {
  it("admin sees every staff page", () => {
    const hrefs = navForRole("admin").map((n) => n.href);
    for (const h of ["/admin/dashboard", "/admin/live", "/admin/enrollment", "/admin/users", "/admin/analytics", "/admin/inspector", "/admin/search", "/admin/students", "/admin/system", "/admin/cameras", "/security/monitor"]) expect(hrefs).toContain(h);
    expect(hrefs.some((h) => h.startsWith("/student"))).toBe(false);
  });

  it("operator cannot see admin-only pages", () => {
    const hrefs = navForRole("operator").map((n) => n.href);
    expect(hrefs).toContain("/security/monitor");
    expect(hrefs).toContain("/admin/live");
    for (const h of ["/admin/users", "/admin/enrollment", "/admin/inspector"]) expect(hrefs).not.toContain(h);
  });

  it("student only sees student pages", () => {
    expect(navForRole("student").map((n) => n.href)).toEqual(["/student/dashboard", "/student/attendance", "/student/profile"]);
  });

  it("canAccess mirrors the navigation and denies unknown routes", () => {
    expect(canAccess("admin", "/admin/users")).toBe(true);
    expect(canAccess("operator", "/admin/users")).toBe(false);
    expect(canAccess("student", "/admin/dashboard")).toBe(false);
    expect(canAccess("student", "/student/attendance")).toBe(true);
    expect(canAccess("admin", "/nope")).toBe(false);
  });

  it("each role lands on a page it may open", () => {
    for (const r of ["admin", "operator", "student"] as const) expect(canAccess(r, homeFor(r))).toBe(true);
  });
});
