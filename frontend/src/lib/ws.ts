"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export const NO_RETRY_CODES = [4401, 4403, 4409];

export const backoffDelay = (attempt: number): number => Math.min(500 * 2 ** attempt, 10000);

export function wsUrl(path: string): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env) return env.replace(/\/$/, "") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = process.env.NODE_ENV === "production" ? window.location.host : `${window.location.hostname}:8000`;
  return `${proto}//${host}${path}`;
}

export type SocketState = "connecting" | "open" | "reconnecting" | "failed" | "idle";

interface Options {
  enabled?: boolean;
  onMessage?: (data: unknown) => void;
  onOpen?: () => void;
  parseJson?: boolean;
}

/** WebSocket with exponential-backoff reconnect. Stops for auth/forbidden/no-session close codes. */
export function useReconnectingSocket(path: string, { enabled = true, onMessage, onOpen, parseJson = true }: Options = {}) {
  const [state, setState] = useState<SocketState>("idle");
  const [attempts, setAttempts] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const msgRef = useRef(onMessage);
  const openRef = useRef(onOpen);
  msgRef.current = onMessage;
  openRef.current = onOpen;

  useEffect(() => {
    if (!enabled) { setState("idle"); return; }
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (cancelled) return;
      setState(attempt === 0 ? "connecting" : "reconnecting");
      const ws = new WebSocket(wsUrl(path));
      wsRef.current = ws;
      ws.onopen = () => {
        if (cancelled) return;
        attempt = 0;
        setAttempts(0);
        setState("open");
        openRef.current?.();
      };
      ws.onmessage = (ev: MessageEvent) => {
        if (!msgRef.current) return;
        if (parseJson && typeof ev.data === "string") {
          try { msgRef.current(JSON.parse(ev.data)); } catch { /* ignore malformed frame */ }
        } else msgRef.current(ev.data);
      };
      ws.onclose = (ev: CloseEvent) => {
        if (cancelled) return;
        wsRef.current = null;
        if (NO_RETRY_CODES.includes(ev.code)) { setState("failed"); return; }
        const delay = backoffDelay(attempt);
        attempt += 1;
        setAttempts(attempt);
        setState("reconnecting");
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => { /* onclose follows and drives the retry */ };
    };

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) { ws.onclose = null; ws.onmessage = null; ws.onerror = null; try { ws.close(); } catch { /* already closed */ } }
    };
  }, [path, enabled, parseJson]);

  const send = useCallback((data: string | Blob | ArrayBuffer): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== 1) return false;
    ws.send(data);
    return true;
  }, []);

  const bufferedAmount = useCallback(() => wsRef.current?.bufferedAmount ?? 0, []);

  return { state, attempts, send, bufferedAmount };
}
