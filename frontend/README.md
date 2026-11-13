# FaceAttend frontend (Next.js App Router)

React UI for the face-attendance system. It talks to the FastAPI backend through the contract in
`../docs/API_CONTRACT.md`. All data comes from the API; nothing is hardcoded.

> **Honest status:** this code was written in an environment with no network access, so
> `npm install`, `next build`, `tsc`, `eslint` and `vitest` were **never run**. Only a syntax-level
> parse (TypeScript 7 `tsc` without type libraries) was possible. Expect to fix a few type or lint
> errors on the first `npm run typecheck`. Dependency versions are pinned to releases the author
> believes are mutually compatible (Next 14.2, React 18.3, Tailwind 3.4, framer-motion 11) but could
> not be resolved against the registry.

## Run

```bash
cd frontend
cp .env.example .env.local        # BACKEND_URL (default http://127.0.0.1:8000)
npm install
npm run dev                       # http://localhost:3000
```

Other commands: `npm run typecheck`, `npm run lint`, `npm test` (vitest), `npm run build && npm start`.

The backend must be running (`uvicorn` on port 8000). `/api/*` is proxied by Next (same-origin cookies
and CSRF). Next.js rewrites cannot proxy WebSockets, so the browser connects to `/ws/*` directly:
`NEXT_PUBLIC_WS_URL` if set, else `<host>:8000` in development, else the same host in production
(put a reverse proxy in front that routes `/ws` and `/api` to the API and everything else to Next).

First start: open `/login`; if no admin exists the page shows the first-run setup form and asks for the
one-time setup token printed in the API server log.

## Structure

- `src/lib` API client (CSRF header, typed errors), auth context, reconnecting WebSocket hook,
  camera helpers, role navigation, status colours.
- `src/components/ui` glass design system: GlassCard/Button/Modal/Table/StatCard/ChartCard, StatusBadge,
  SearchInput, Tabs, EmptyState, Skeleton, Toast. `layout/` has sidebar, topbar, app shell.
- `src/app` routes: `/login`, `/admin/*`, `/student/*`, `/security/monitor`.
- `tests/` vitest: login form, role navigation, table filtering, API error states, WebSocket reconnect.

## Security notes

Route guards in the browser are convenience only; the server enforces roles on every route and
WebSocket. Session is an HTTP-only cookie, no tokens are stored in localStorage (only the theme).
Embeddings and RTSP credentials are never present in API responses, so the UI never handles them.
