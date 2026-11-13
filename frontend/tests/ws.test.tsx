import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { backoffDelay, useReconnectingSocket } from "@/lib/ws";

class FakeWS {
  static instances: FakeWS[] = [];
  readyState = 0;
  bufferedAmount = 0;
  sent: unknown[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeWS.instances.push(this); }
  send(d: unknown) { this.sent.push(d); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
  drop(code = 1006) { this.readyState = 3; this.onclose?.({ code }); }
}

beforeEach(() => { FakeWS.instances = []; vi.useFakeTimers(); vi.stubGlobal("WebSocket", FakeWS); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("backoffDelay", () => {
  it("doubles from 500 ms and caps at 10 s", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(backoffDelay)).toEqual([500, 1000, 2000, 4000, 8000, 10000, 10000, 10000]);
  });
});

describe("useReconnectingSocket", () => {
  it("connects, delivers parsed JSON and reports open", () => {
    const onMessage = vi.fn();
    const { result } = renderHook(() => useReconnectingSocket("/ws/events", { onMessage }));
    expect(result.current.state).toBe("connecting");
    act(() => FakeWS.instances[0].open());
    expect(result.current.state).toBe("open");
    act(() => FakeWS.instances[0].onmessage?.({ data: JSON.stringify({ kind: "status" }) }));
    expect(onMessage).toHaveBeenCalledWith({ kind: "status" });
    act(() => FakeWS.instances[0].onmessage?.({ data: "not json" }));          // ignored, no throw
    expect(onMessage).toHaveBeenCalledTimes(1);
  });

  it("reconnects with exponential backoff and resets after a successful open", () => {
    const { result } = renderHook(() => useReconnectingSocket("/ws/events"));
    act(() => FakeWS.instances[0].open());
    act(() => FakeWS.instances[0].drop());
    expect(result.current.state).toBe("reconnecting");
    expect(FakeWS.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(499); });
    expect(FakeWS.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(FakeWS.instances).toHaveLength(2);

    act(() => FakeWS.instances[1].drop());                                    // second failure: 1000 ms
    act(() => { vi.advanceTimersByTime(999); });
    expect(FakeWS.instances).toHaveLength(2);
    act(() => { vi.advanceTimersByTime(1); });
    expect(FakeWS.instances).toHaveLength(3);
    expect(result.current.attempts).toBe(2);

    act(() => FakeWS.instances[2].open());                                    // success resets the backoff
    expect(result.current.state).toBe("open");
    expect(result.current.attempts).toBe(0);
    act(() => FakeWS.instances[2].drop());
    act(() => { vi.advanceTimersByTime(500); });
    expect(FakeWS.instances).toHaveLength(4);
  });

  it.each([4401, 4403, 4409])("does not retry on close code %i", (code) => {
    const { result } = renderHook(() => useReconnectingSocket("/ws/preview"));
    act(() => FakeWS.instances[0].open());
    act(() => FakeWS.instances[0].drop(code));
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(FakeWS.instances).toHaveLength(1);
    expect(result.current.state).toBe("failed");
  });

  it("does nothing while disabled and closes on unmount without reconnecting", () => {
    const { rerender, unmount } = renderHook(({ enabled }) => useReconnectingSocket("/ws/preview", { enabled }), { initialProps: { enabled: false } });
    expect(FakeWS.instances).toHaveLength(0);
    rerender({ enabled: true });
    expect(FakeWS.instances).toHaveLength(1);
    act(() => FakeWS.instances[0].open());
    unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(FakeWS.instances).toHaveLength(1);
  });

  it("sends only while open", () => {
    const { result } = renderHook(() => useReconnectingSocket("/ws/browser-camera"));
    expect(result.current.send("x")).toBe(false);
    act(() => FakeWS.instances[0].open());
    expect(result.current.send("x")).toBe(true);
    expect(FakeWS.instances[0].sent).toEqual(["x"]);
  });
});
