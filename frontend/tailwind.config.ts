import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), fg: v("fg"), muted: v("muted"), surface: v("surface"), line: v("line"),
        primary: v("primary"), accent: v("accent"), success: v("success"), warn: v("warn"),
        danger: v("danger"), purple: v("purple"), orange: v("orange"), info: v("info"),
      },
      borderRadius: { xl2: "1.25rem" },
      boxShadow: { glow: "0 0 0 1px rgb(var(--primary) / 0.35), 0 8px 40px -8px rgb(var(--primary) / 0.45)" },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        float: { "0%,100%": { transform: "translate3d(0,0,0)" }, "50%": { transform: "translate3d(30px,-40px,0)" } },
        scan: { "0%": { top: "0%" }, "100%": { top: "100%" } },
        spoof: { "0%,100%": { boxShadow: "0 0 0 0 rgb(239 68 68 / 0.7)" }, "50%": { boxShadow: "0 0 0 10px rgb(239 68 68 / 0)" } },
        livepulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
      },
      animation: {
        shimmer: "shimmer 1.6s infinite",
        float: "float 14s ease-in-out infinite",
        scan: "scan 2.2s linear infinite alternate",
        spoof: "spoof 1.1s ease-out infinite",
        livepulse: "livepulse 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
