"use client";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { LiveEvent, LiveStatus } from "./types";
import { useReconnectingSocket, type SocketState } from "./ws";

interface FeedCtx { events: LiveEvent[]; status: LiveStatus | null; socket: SocketState }
const Ctx = createContext<FeedCtx>({ events: [], status: null, socket: "idle" });

type Msg = { kind: "event"; event: LiveEvent } | { kind: "status"; status: LiveStatus };

/** One /ws/events subscription shared by the topbar, live page and security monitor. */
export function LiveFeedProvider({ children, enabled }: { children: ReactNode; enabled: boolean }) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const onMessage = useCallback((m: unknown) => {
    const msg = m as Msg;
    if (msg.kind === "event") setEvents((prev) => [msg.event, ...prev].slice(0, 100));
    else if (msg.kind === "status") setStatus(msg.status);
  }, []);
  const { state } = useReconnectingSocket("/ws/events", { enabled, onMessage });
  const value = useMemo(() => ({ events, status, socket: state }), [events, status, state]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useLiveFeed = () => useContext(Ctx);
