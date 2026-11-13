"use client";
import { Moon, Sun } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { THEME_KEY } from "@/lib/theme-script";

export function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("light") ? "light" : "dark");
  }, []);
  const toggle = useCallback(() => {
    const next = document.documentElement.classList.contains("light") ? "dark" : "light";
    document.documentElement.classList.toggle("light", next === "light");
    setTheme(next);
    try { localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable: theme just won't persist */ }
  }, []);
  return { theme, toggle };
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button type="button" onClick={toggle} aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className="rounded-xl p-2 text-muted transition hover:bg-[var(--glass-strong)] hover:text-fg">
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
