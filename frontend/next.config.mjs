/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // REST goes through the Next.js proxy so the browser stays same-origin (cookie + CSRF).
  // WebSockets are NOT proxied by Next rewrites: src/lib/ws.ts connects to NEXT_PUBLIC_WS_URL,
  // or to <host>:8000 in development, or to the same host behind a reverse proxy in production.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
