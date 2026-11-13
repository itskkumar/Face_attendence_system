import type { Metadata } from "next";
import type { ReactNode } from "react";
import { THEME_INIT_SCRIPT } from "@/lib/theme-script";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = { title: "FaceAttend", description: "Face attendance with anti-spoofing" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} /></head>
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
