"""
video_sources.py - uniform readers for webcam, RTSP and recorded video.

  * LiveGrabber : background thread that always keeps only the NEWEST frame, so a
                  slow consumer drops frames instead of falling seconds behind
                  (the classic RTSP buffer-lag problem). Reconnects with backoff.
  * FileReader  : sequential, lossless - every frame is delivered (max accuracy).
  * FpsLimiter  : caps the processing rate to keep a fanless Mac cool.

All readers expose:  read() -> (ok, frame_bgr),  release(),  describe()
"""
from __future__ import annotations

import threading
import time
from typing import Optional, Tuple, Union

import cv2
import numpy as np

import config  # noqa: F401  (sets OpenCV environment variables before any capture opens)


class FpsLimiter:
    def __init__(self, fps: float):
        self.interval = 1.0 / fps if fps and fps > 0 else 0.0
        self._next = time.perf_counter()

    def wait(self) -> None:
        if not self.interval:
            return
        now = time.perf_counter()
        if now < self._next:
            time.sleep(self._next - now)
            self._next += self.interval
        else:
            self._next = now + self.interval


class LiveGrabber:
    def __init__(self, source: Union[int, str], label: str = "camera"):
        self.source = source
        self.label = label
        self.is_live = True
        self.total_frames = 0
        self.last_error: Optional[str] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._seq = 0
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._opened_once = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"grabber-{label}")

    # ---- lifecycle
    def start(self, wait_s: float = 8.0) -> "LiveGrabber":
        self._thread.start()
        self._opened_once.wait(timeout=wait_s)
        return self

    def release(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._thread.join(timeout=3.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        return f"{self.label} ({self.source})"

    # ---- consumer API
    def read(self, timeout: float = 2.0) -> Tuple[bool, Optional[np.ndarray]]:
        """Block until a frame NEWER than the last one returned is available."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._seq == getattr(self, "_delivered", 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._stop.is_set():
                    return False, None
                self._cond.wait(remaining)
            self._delivered = self._seq
            return True, self._frame

    # ---- worker
    def _open(self) -> bool:
        if isinstance(self.source, str):
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(int(self.source))
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._cap = cap
            self.last_error = None
            return True
        cap.release()
        self.last_error = (
            f"Could not open {self.describe()}. On macOS, allow camera access for your terminal "
            "(System Settings > Privacy & Security > Camera), then fully restart the terminal. "
            "For RTSP, verify the URL in VLC first."
        )
        return False

    def _run(self) -> None:
        backoff, failures = 1.0, 0
        while not self._stop.is_set():
            if self._cap is None:
                ok = self._open()
                self._opened_once.set()
                if not ok:
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 15.0)
                    continue
                backoff, failures = 1.0, 0
            ok, frame = self._cap.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 5:                      # stream dropped -> reconnect
                    self._cap.release()
                    self._cap = None
                else:
                    time.sleep(0.02)
                continue
            failures = 0
            with self._cond:
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()


class FileReader:
    def __init__(self, path: str, loop: bool = False):
        self.path = path
        self.loop = loop
        self.is_live = False
        self.last_error: Optional[str] = None
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            self.last_error = f"Could not open video file: {path}"
        self.total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.native_fps = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)

    def start(self) -> "FileReader":
        return self

    @property
    def opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.opened:
            return False, None
        ok, frame = self._cap.read()
        if not ok and self.loop:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        return (True, frame) if ok and frame is not None else (False, None)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        return f"video file ({self.path})"


def open_source(kind: str, target: Union[int, str], loop: bool = False):
    """kind: 'webcam' | 'rtsp' | 'file'. Returns a started reader (check .last_error)."""
    if kind == "file":
        return FileReader(str(target), loop=loop).start()
    label = "webcam" if kind == "webcam" else "rtsp"
    return LiveGrabber(int(target) if kind == "webcam" else str(target), label=label).start()
