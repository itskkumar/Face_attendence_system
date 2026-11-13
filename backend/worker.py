"""
backend/worker.py - the gate worker PROCESS.

One process owns exactly one FaceEngine and one PAD session and runs the (frozen) GatePipeline on a
camera / file / browser stream, independent of any browser page. The API talks to it over a
localhost-only, authkey-authenticated multiprocessing connection (key file data/worker.key, mode 0600).

    python -m backend.worker            # normally started by scripts/start_all or by hand

Safety properties
  * single instance: an exclusive flock on data/worker.lock (double starts / uvicorn --reload cannot
    create a second engine); the second process exits with a clear message
  * bounded everything: command queue (64), preview = only the LATEST frame, browser frames = only the
    LATEST frame (stale frames are dropped and counted), events deque (200)
  * preview JPEGs are produced only while the API says someone is watching, capped at preview_fps
  * RTSP URLs are resolved here from the camera repo; they are never sent to the API/browser
  * no embeddings ever leave this process
"""
from __future__ import annotations

import dataclasses
import fcntl
import logging
import os
import queue
import secrets
import threading
import time
from collections import deque
from multiprocessing.connection import Client, Listener
from typing import Callable, Deque, Dict, Optional

import cv2
import numpy as np

import antispoof
from config import DATA_DIR, DB_PATH, DEFAULT_SETTINGS, Settings
from database import Store

log = logging.getLogger("worker")
HOST = "127.0.0.1"
KEY_PATH = os.path.join(DATA_DIR, "worker.key")
LOCK_PATH = os.path.join(DATA_DIR, "worker.lock")
DEFAULT_PORT = int(os.environ.get("WORKER_PORT", "8765"))

TUNABLE = {"similarity_threshold": float, "min_blur_var": float, "min_pose_score": float, "detect_every_n": int,
           "cooldown_seconds": int, "gate_line_enabled": bool, "gate_line_orientation": str,
           "gate_line_ratio": float, "liveness_mode": str}
VALID = {"liveness_mode": {"off", "fft_experimental", "minifas"}, "gate_line_orientation": {"horizontal", "vertical"}}


def load_or_create_key(path: str = KEY_PATH) -> bytes:
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    return open(path, "rb").read()


class WorkerAlreadyRunning(RuntimeError):
    pass


class SingleInstance:
    def __init__(self, path: str = LOCK_PATH):
        self._f = open(path, "w")
        try:
            fcntl.flock(self._f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise WorkerAlreadyRunning("another gate worker already holds " + path)
        self._f.write(str(os.getpid())); self._f.flush()


def apply_tuning(base: Settings, patch: dict) -> Settings:
    """Validated Partial<Tuning> -> new Settings via dataclasses.replace (existing defaults untouched)."""
    clean = {}
    for k, v in (patch or {}).items():
        if k not in TUNABLE:
            raise ValueError(f"unknown setting {k}")
        v = TUNABLE[k](v) if TUNABLE[k] is not bool else bool(v)
        if k in VALID and v not in VALID[k]:
            raise ValueError(f"invalid value for {k}")
        clean[k] = v
    for k, lo, hi in (("similarity_threshold", 0.1, 0.99), ("min_blur_var", 0, 1000), ("min_pose_score", 0, 1),
                      ("detect_every_n", 1, 30), ("cooldown_seconds", 0, 86400), ("gate_line_ratio", 0.05, 0.95)):
        if k in clean and not lo <= clean[k] <= hi:
            raise ValueError(f"{k} must be between {lo} and {hi}")
    return dataclasses.replace(base, **clean)


class BrowserSource:
    """Holds only the newest JPEG pushed by the browser; older undecoded frames are dropped."""

    def __init__(self):
        self._lock, self._jpeg, self.dropped, self.last_frame_t = threading.Lock(), None, 0, 0.0

    def push(self, jpeg: bytes) -> None:
        with self._lock:
            if self._jpeg is not None:
                self.dropped += 1
            self._jpeg = jpeg

    def read(self):
        with self._lock:
            j, self._jpeg = self._jpeg, None
        if j is None:
            return False, None
        img = cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return False, None
        self.last_frame_t = time.time()
        return True, img

    def release(self): pass
    def describe(self): return "browser camera"


class GateWorker:
    def __init__(self, store: Store, base_settings: Settings, resolve_camera: Callable[[str], tuple],
                 engine_factory: Callable[[Settings], object], pad_factory: Callable[[Settings], antispoof.PADProvider],
                 open_source: Callable, send: Callable[[tuple], None], pipeline_cls=None,
                 preview_fps: float = 12.0, preview_width: int = 960, preview_quality: int = 70):
        from pipeline import GatePipeline
        self.store, self.base, self.settings = store, base_settings, base_settings
        self.resolve_camera, self.engine_factory, self.pad_factory = resolve_camera, engine_factory, pad_factory
        self.open_source, self.send = open_source, send
        self.pipeline_cls = pipeline_cls or GatePipeline
        self.preview_fps, self.preview_width, self.preview_quality = preview_fps, preview_width, preview_quality
        self.engine = None                       # exactly one engine per process (lazy)
        self.pad: Optional[antispoof.PADProvider] = None   # exactly one PAD session per process (lazy)
        self.pipeline = None
        self.source = None
        self.browser: Optional[BrowserSource] = None
        self.watching = False
        self.error: Optional[str] = None
        self.camera_label, self.source_label, self.kind = "", "", ""
        self.last_info: Dict = {}
        self.events: Deque[dict] = deque(maxlen=200)
        self._last_preview = self._last_status = 0.0
        self._start_args: Optional[dict] = None
        from backend.enroll_rpc import EnrollmentService
        self.enroll = EnrollmentService(store, self._engine_for_rpc, self._pad_for_rpc, lambda: self.settings,
                                        require_liveness=os.environ.get("ENROLL_REQUIRE_LIVENESS") == "1")

    def _engine_for_rpc(self):
        self._ensure_models(self.settings)
        return self.engine

    def _pad_for_rpc(self):
        self._ensure_models(self.settings)
        # enrollment checks the REAL provider even while live liveness_mode is "off"
        if isinstance(self.pad, antispoof.NullPAD):
            self.pad = antispoof.MiniFASNetPAD()
        return self.pad

    def _rpc(self, rid: int, name: str, args: tuple) -> None:
        from backend.enroll_rpc import EnrollError
        fn = {"enroll_status": self.enroll.status, "enroll_open": self.enroll.open, "enroll_sample": self.enroll.sample,
              "enroll_finish": self.enroll.finish, "enroll_cancel": self.enroll.cancel, "enroll_photos": self.enroll.photos}.get(name)
        try:
            if fn is None:
                raise EnrollError("unknown rpc")
            self.send(("rpc_result", rid, {"ok": True, "result": fn(*args)}))
        except EnrollError as exc:
            self.send(("rpc_result", rid, {"ok": False, "error": str(exc), "code": 400}))
        except Exception as exc:
            log.exception("rpc %s failed", name)
            self.send(("rpc_result", rid, {"ok": False, "error": f"{type(exc).__name__}: {exc}", "code": 500}))

    # ---- lifecycle
    def _ensure_models(self, settings: Settings) -> None:
        if self.engine is None:
            self.engine = self.engine_factory(settings)
        if self.pad is None or (settings.liveness_mode == "minifas" and isinstance(self.pad, antispoof.NullPAD)):
            self.pad = self.pad_factory(settings)

    def _sink(self, ev: dict) -> None:
        self.events.appendleft(ev)
        self.send(("event", ev))

    def start(self, cfg: dict) -> None:
        self.stop()
        try:
            settings = apply_tuning(self.base, cfg.get("settings") or {})
            kind = cfg["source"]
            self._ensure_models(settings)
            if kind == "browser":
                self.browser = self.source = BrowserSource()
                self.source_label, label = "browser camera", cfg.get("camera_label") or "browser"
                is_file = False
            else:
                if kind == "camera":
                    ctype, target = self.resolve_camera(cfg["camera_id"])
                    label = cfg.get("camera_label") or cfg["camera_id"]
                elif kind == "server_webcam":
                    ctype, target, label = "webcam", int(cfg.get("webcam_index", 0)), cfg.get("camera_label") or "server-webcam"
                elif kind == "file":
                    ctype, target, label = "file", cfg["file_path"], cfg.get("camera_label") or "video-file"
                else:
                    raise ValueError("unknown source")
                ctype = "rtsp" if ctype == "http" else ctype
                self.source = self.open_source(ctype, target, loop=bool(cfg.get("loop")))
                err = getattr(self.source, "last_error", None)
                if err:
                    raise RuntimeError(f"could not open source: {err}")
                self.source_label = "file" if ctype == "file" else ctype            # never the URL
                is_file = ctype == "file"
            self.settings, self.camera_label, self.kind = settings, label, kind
            self.pipeline = self.pipeline_cls(self.engine, self.store, settings, source_label=self.source_label,
                                              is_file=is_file, camera_label=label,
                                              pad=self.pad if settings.liveness_mode == "minifas" else None,
                                              event_sink=self._sink)
            self._start_args, self.error = cfg, None
            self._sink({"event_id": os.urandom(8).hex(), "type": "camera.state", "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "camera_id": label, "track_id": -1, "status": "live", "pad_state": None, "pad_real_prob": None,
                        "liveness_mode": settings.liveness_mode})
        except Exception as exc:
            log.exception("start failed")
            self.error = f"{type(exc).__name__}: {exc}"
            self._teardown()

    def _teardown(self) -> None:
        if self.pipeline is not None:
            try:
                self.pipeline.close()
            except Exception:
                log.exception("pipeline close")
        if self.source is not None:
            try:
                self.source.release()
            except Exception:
                log.exception("source release")
        self.pipeline = self.source = self.browser = None

    def stop(self) -> None:
        self._teardown()
        self.last_info = {}

    @property
    def running(self) -> bool:
        return self.pipeline is not None

    def pad_health(self) -> dict:
        if self.pad is not None:
            return self.pad.health()
        return antispoof.build_pad(self.settings if self.settings.liveness_mode == "minifas" else dataclasses.replace(
            self.settings, liveness_mode="off")).health()

    def status(self) -> dict:
        i = self.last_info
        return {"running": self.running, "source_label": self.source_label, "camera_label": self.camera_label,
                "fps": round(i.get("fps", 0.0), 1), "proc_ms": round(i.get("proc_ms", 0.0), 1),
                "det_ms": round(i.get("det_ms", 0.0), 1), "rec_ms": round(i.get("rec_ms", 0.0), 1),
                "pad_ms": round(i.get("pad_ms", 0.0), 1), "faces": i.get("faces", 0),
                "session_logged": getattr(self.pipeline, "session_logged", 0), "provider": getattr(self.engine, "provider_label", ""),
                "liveness_mode": self.settings.liveness_mode, "pad": self.pad_health(),
                "settings": {k: getattr(self.settings, k) for k in TUNABLE}, "error": self.error,
                "browser_dropped": self.browser.dropped if self.browser else 0}

    # ---- commands
    def handle(self, cmd: tuple) -> None:
        name = cmd[0]
        if name == "start":
            self.start(cmd[1])
        elif name == "stop":
            self.stop()
        elif name == "settings":
            try:
                new = apply_tuning(self.settings, cmd[1])
            except ValueError as exc:
                self.error = str(exc)
            else:
                cfg = dict(self._start_args or {})
                if self.running:
                    merged = dict(cfg.get("settings") or {}); merged.update(cmd[1]); cfg["settings"] = merged
                    self.start(cfg)
                else:
                    self.base = self.settings = new
        elif name == "watch":
            self.watching = bool(cmd[1])
        elif name == "frame" and self.browser is not None:
            self.browser.push(cmd[1])
        elif name == "status":
            self.send(("status", self.status()))
        elif name == "events":
            self.send(("events", list(self.events)[: int(cmd[1])]))
        elif name == "rpc":
            self._rpc(cmd[1], cmd[2], cmd[3])
        elif name == "shutdown":
            self.stop(); raise SystemExit

    # ---- main step
    def tick(self) -> bool:
        """Process at most one frame. Returns True if a frame was processed."""
        now = time.time()
        if now - self._last_status > 1.0:
            self._last_status = now
            self.send(("status", self.status()))
        if not self.running:
            return False
        try:
            ok, frame = self.source.read()
        except Exception as exc:
            self.error = f"read failed: {exc}"
            return False
        if not ok or frame is None:
            if self.kind == "file" and getattr(self.source, "opened", lambda: True)() is False:
                self._sink({"event_id": os.urandom(8).hex(), "type": "camera.state", "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "camera_id": self.camera_label, "track_id": -1, "status": "ended", "pad_state": None,
                            "pad_real_prob": None, "liveness_mode": self.settings.liveness_mode})
                self.stop()
            return False
        try:
            out, info = self.pipeline.process(frame)
        except Exception as exc:
            log.exception("pipeline error")
            self.error = f"pipeline error: {type(exc).__name__}: {exc}"
            return False
        self.last_info = info
        if self.watching and now - self._last_preview >= 1.0 / self.preview_fps:
            self._last_preview = now
            self.send(("frame", self._preview(out, info)))
        return True

    def _preview(self, out: np.ndarray, info: dict) -> dict:
        h, w = out.shape[:2]
        scale = min(1.0, self.preview_width / float(w))
        if scale < 1.0:
            out = cv2.resize(out, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, self.preview_quality])
        tracks = [dict(t, bbox=[round(v * scale, 1) for v in t["bbox"]]) for t in info.get("tracks", [])]
        return {"jpeg": buf.tobytes() if ok else b"", "width": out.shape[1], "height": out.shape[0], "tracks": tracks,
                "fps": round(info.get("fps", 0.0), 1), "proc_ms": round(info.get("proc_ms", 0.0), 1)}


# ------------------------------------------------------------------------------------ transport
class Transport:
    """Accepts one authenticated API connection at a time; commands go to a bounded queue."""

    def __init__(self, port: int = DEFAULT_PORT, key: Optional[bytes] = None):
        self.listener = Listener((HOST, port), authkey=key or load_or_create_key())
        self.cmds: "queue.Queue[tuple]" = queue.Queue(maxsize=64)
        self.conn, self._lock, self.on_frame = None, threading.Lock(), None
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                conn = self.listener.accept()
            except Exception:
                continue                                   # failed authkey handshakes land here
            with self._lock:
                old, self.conn = self.conn, conn
            if old:
                try: old.close()
                except Exception: pass
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn) -> None:
        while True:
            try:
                cmd = conn.recv()
            except (EOFError, OSError):
                with self._lock:
                    if self.conn is conn:
                        self.conn = None
                        self.cmds_put(("watch", False))
                return
            if cmd and cmd[0] == "frame" and self.on_frame:
                self.on_frame(cmd[1])                      # newest-wins, no queueing
            else:
                self.cmds_put(cmd)

    def cmds_put(self, cmd) -> None:
        try:
            self.cmds.put_nowait(cmd)
        except queue.Full:
            log.warning("command queue full, dropping %s", cmd[0] if cmd else cmd)

    def send(self, msg: tuple) -> None:
        with self._lock:
            conn = self.conn
        if conn is None:
            return
        try:
            conn.send(msg)
        except Exception:
            with self._lock:
                if self.conn is conn:
                    self.conn = None


def run(port: int = DEFAULT_PORT) -> None:                       # pragma: no cover - needs real models
    logging.basicConfig(level=logging.INFO)
    lock = SingleInstance()                                        # noqa: F841 (held for process lifetime)
    from face_engine import FaceEngine
    from video_sources import open_source
    from backend.services import CameraRepo
    store = Store(DB_PATH)
    repo = CameraRepo(os.path.join(DATA_DIR, "cameras.json"))
    tr = Transport(port)
    w = GateWorker(store, DEFAULT_SETTINGS, repo.get_source, FaceEngine, antispoof.build_pad, open_source, tr.send)
    log.info("gate worker ready on %s:%s", HOST, port)
    while True:
        try:
            while True:
                w.handle(tr.cmds.get_nowait())
        except queue.Empty:
            pass
        except SystemExit:
            return
        if w.browser is not None:
            tr.on_frame = w.browser.push
        else:
            tr.on_frame = None
        if not w.tick():
            time.sleep(0.01)


if __name__ == "__main__":
    run()
