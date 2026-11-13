import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, errorMessage, setCsrf } from "@/lib/api";
import { jsonResponse } from "./helpers";

afterEach(() => { vi.unstubAllGlobals(); setCsrf(null); });

describe("api client error states", () => {
  it("throws ApiError with the server detail and status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Not enough permissions" }, 403)));
    await expect(api("/users")).rejects.toMatchObject({ name: "ApiError", status: 403, message: "Not enough permissions" });
  });

  it("flattens FastAPI 422 validation arrays", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: [{ msg: "field required" }, { msg: "too short" }] }, 422)));
    await expect(api("/users", { method: "POST", body: {} })).rejects.toThrow("field required; too short");
  });

  it("reports an unreachable server as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = (await api("/dashboard").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(errorMessage(err)).toMatch(/Cannot reach the server/);
  });

  it("falls back to a generic message for non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(api("/dashboard")).rejects.toThrow("Request failed (502)");
  });

  it("sends the CSRF header on non-GET requests only", async () => {
    const f = vi.fn().mockImplementation(async () => jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", f);
    setCsrf("tok123");
    await api("/students/R1", { method: "DELETE" });
    await api("/students");
    expect((f.mock.calls[0][1].headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect((f.mock.calls[1][1].headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("uses same-origin credentials and JSON bodies", async () => {
    const f = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", f);
    await api("/auth/login", { method: "POST", body: { username: "a", password: "b" } });
    expect(f.mock.calls[0][0]).toBe("/api/auth/login");
    expect(f.mock.calls[0][1].credentials).toBe("same-origin");
    expect(f.mock.calls[0][1].body).toBe(JSON.stringify({ username: "a", password: "b" }));
  });
});
