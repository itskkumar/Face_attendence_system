"""backend/worker_client.py - API-side link to the gate worker process (localhost, authkey, bounded)."""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from multiprocessing.connection import Client
from typing import Optional

from backend import worker as W


class WorkerUnavailable(Exception):
    pass


class WorkerError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


class WorkerClient:
    def __init__(self, port: int = W.DEFAULT_PORT, key: Optional[bytes] = None):
        self.port, self.key = port, key
        self._conn, self._lock = None, threading.Lock()
        self.status: dict = {}
        self.status_t = 0.0
        self.frame: Optional[dict] = None
        self.frame_seq = 0
        self.events = deque(maxlen=200)
        self.event_seq = 0
        self._rpc_ids, self._waiters = itertools.count(1), {}
        self._viewers = 0

    # ---- connection
    def _connect(self):
        with self._lock:
            if self._conn is not None:
                return self._conn
            try:
                conn = Client((W.HOST, self.port), authkey=self.key or W.load_or_create_key())
            except Exception as exc:
                raise WorkerUnavailable("Gate worker is not running. Start it with: python -m backend.worker") from exc
            self._conn = conn
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()
            if self._viewers:
                conn.send(("watch", True))
            conn.send(("status",))
            return conn

    def _read(self, conn) -> None:
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                with self._lock:
                    if self._conn is conn:
                        self._conn = None
                        self.status = {}
                for ev in self._waiters.values():
                    ev["done"].set()
                return
            kind = msg[0]
            if kind == "status":
                self.status, self.status_t = msg[1], time.time()
            elif kind == "event":
                self.event_seq += 1
                self.events.append((self.event_seq, msg[1]))
            elif kind == "frame":
                self.frame, self.frame_seq = msg[1], self.frame_seq + 1
            elif kind == "events":
                for e in reversed(msg[1]):
                    pass
            elif kind == "rpc_result":
                w = self._waiters.get(msg[1])
                if w:
                    w["res"] = msg[2]
                    w["done"].set()

    def send(self, cmd: tuple) -> None:
        conn = self._connect()
        try:
            conn.send(cmd)
        except Exception as exc:
            with self._lock:
                self._conn = None
            raise WorkerUnavailable("Lost connection to the gate worker.") from exc

    def available(self) -> bool:
        try:
            self._connect()
            return True
        except WorkerUnavailable:
            return False

    def rpc(self, name: str, *args, timeout: float = 30.0):
        rid = next(self._rpc_ids)
        w = self._waiters[rid] = {"done": threading.Event(), "res": None}
        try:
            self.send(("rpc", rid, name, args))
            if not w["done"].wait(timeout):
                raise WorkerError("Gate worker did not answer in time.", 504)
            res = w["res"]
            if res is None:
                raise WorkerUnavailable("Lost connection to the gate worker.")
            if not res["ok"]:
                raise WorkerError(res["error"], res.get("code", 400))
            return res["result"]
        finally:
            self._waiters.pop(rid, None)

    # ---- viewers (preview only while someone watches)
    def viewer(self, delta: int) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers + delta)
            watching = self._viewers > 0
        try:
            self.send(("watch", watching))
        except WorkerUnavailable:
            pass

    @property
    def viewers(self) -> int:
        return self._viewers

    def refresh_status(self) -> dict:
        self.send(("status",))
        return self.status
