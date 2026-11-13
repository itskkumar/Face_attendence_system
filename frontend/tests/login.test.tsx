import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/components/features/login-form";
import { AuthProvider } from "@/lib/auth";
import { getCsrf, setCsrf } from "@/lib/api";
import { jsonResponse } from "./helpers";

afterEach(() => { vi.unstubAllGlobals(); setCsrf(null); });

function setup(loginResponse: () => Response) {
  const fetchMock = vi.fn(async (url: string) => {
    if (url === "/api/auth/me") return jsonResponse({ detail: "Not authenticated" }, 401);
    if (url === "/api/auth/login") return loginResponse();
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const onSuccess = vi.fn();
  render(<AuthProvider><LoginForm onSuccess={onSuccess} /></AuthProvider>);
  return { fetchMock, onSuccess };
}

describe("LoginForm", () => {
  it("validates required fields without calling the API", async () => {
    const { fetchMock } = setup(() => jsonResponse({}));
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Enter your username")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => u === "/api/auth/login")).toBe(false);
  });

  it("signs in, stores the CSRF token and reports the user", async () => {
    const { onSuccess } = setup(() => jsonResponse({ user: { username: "root", role: "admin", roll_number: null }, csrf_token: "csrf-1", must_reset_password: false }));
    await userEvent.type(screen.getByLabelText("Username"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ username: "root", role: "admin", roll_number: null }));
    expect(getCsrf()).toBe("csrf-1");
  });

  it("shows the server error for bad credentials", async () => {
    const { onSuccess } = setup(() => jsonResponse({ detail: "Invalid username or password" }, 401));
    await userEvent.type(screen.getByLabelText("Username"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("shows a rate-limit message on 429", async () => {
    setup(() => jsonResponse({ detail: "Too many attempts, try again in 60 seconds" }, 429));
    await userEvent.type(screen.getByLabelText("Username"), "root");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
  });
});
