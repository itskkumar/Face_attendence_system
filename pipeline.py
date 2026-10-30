"""
pipeline.py - the per-stream processing engine used by EVERY entry point
(inference.py CLI, Streamlit live page, browser/WebRTC processor).

Per frame
  1. Kalman-predict every track                          (every frame, ~free)
  2. Detect faces + landmarks, ByteTrack-associate       (every Nth frame)
  3. For tracks that are still unidentified, grab a *quality keyframe*:
       size / detector score / pose / blur gates  ->  Umeyama alignment  ->  ArcFace
  4. Vote: a track locks an identity only after several keyframes agree
     (quality-weighted embedding + cosine similarity + best-vs-second margin)
  5. Identified tracks are logged through the cooldown-aware AttendanceLogger,
     and are periodically re-verified so a track-ID swap cannot mislabel anyone
  6. Boxes are drawn EVERY frame from the Kalman state, so they never flicker
     on frames where the detector was skipped
"""
from __future__ import annotations

import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from attendance import AttendanceLogger
from config import Settings
from database import Gallery, Store, StudentInfo
from tracker import ByteTrackLite, Detection, Track
from vision_math import align_face, fft_moire_score, l2_normalize, laplacian_variance, pose_score

GREEN = (113, 204, 46)     # BGR
RED = (60, 60, 230)
AMBER = (0, 190, 255)
DARK = (20, 20, 20)
WHITE = (255, 255, 255)


def ascii_safe(text: str) -> str:
    """OpenCV's built-in fonts only draw ASCII; fold accents and drop the rest."""
    out = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return out or "?"


@dataclass
class Identity:
    status: str = "pending"                 # pending | identified | unknown | spoof
    student: Optional[StudentInfo] = None
    similarity: float = 0.0
    embs: Deque[np.ndarray] = field(default_factory=lambda: deque(maxlen=8))
    quals: Deque[float] = field(default_factory=lambda: deque(maxlen=8))
    votes: Deque[int] = field(default_factory=lambda: deque(maxlen=8))   # student id, -1 = no match
    attempts: int = 0
    last_rec_frame: int = -10 ** 9
    last_verify_frame: int = 0
    mismatches: int = 0
    unknown_since: int = 0
    spoof_votes: int = 0
    ever_unknown: bool = False
    hint: str = ""
    blur: float = 0.0


class GatePipeline:
    def __init__(self, engine, store: Store, settings: Settings, *, source_label: str = "live",
                 is_file: bool = False, logger: Optional[AttendanceLogger] = None,
                 log_attendance: bool = True, camera_label: str = "default"):
        self.engine = engine
        self.store = store
        self.s = settings
        self.log_attendance = log_attendance
        self.camera_label = camera_label
        self.detect_every = max(1, settings.file_detect_every_n if is_file else settings.detect_every_n)
        self.display_stale = max(2 * self.detect_every, 4)
        self.tracker = ByteTrackLite(
            high_thresh=settings.track_high_thresh, low_thresh=settings.track_low_thresh,
            new_thresh=settings.track_new_thresh, match_thresh=settings.track_match_thresh,
            max_age=settings.track_max_age, min_hits=settings.track_min_hits,
            tentative_max_age=max(4, 2 * self.detect_every))
        self.logger = logger or AttendanceLogger(store, settings.cooldown_seconds, source=source_label,
                                                  camera_label=camera_label)
        self.gallery: Gallery = store.load_gallery()
        self._gallery_checked = time.monotonic()
        self.frame_idx = 0
        self.fps = 0.0
        self.proc_ms = 0.0
        self.det_ms = 0.0
        self.rec_ms = 0.0
        self._last_call = None
        self.events: Deque[str] = deque(maxlen=12)
        self.session_logged = 0

    # ------------------------------------------------------------------ main
    def process(self, frame: np.ndarray) -> Tuple[np.ndarray, Dict]:
        t_start = time.perf_counter()
        self.frame_idx += 1
        self._maybe_reload_gallery()
        self.tracker.predict()

        new_events: List[str] = []
        ran_detect = (self.frame_idx - 1) % self.detect_every == 0
        if ran_detect:
            t0 = time.perf_counter()
            dets = self.engine.detect(frame)
            self.tracker.update(dets)
            self._ema("det_ms", (time.perf_counter() - t0) * 1000.0)

            t1 = time.perf_counter()
            h, w = frame.shape[:2]
            for tr in self.tracker.tracks:
                if tr.confirmed and tr.time_since_update == 0:
                    self._update_gate_crossing(tr, w, h)
                    ev = self._recognize(tr, frame)
                    if ev:
                        new_events.append(ev)
            self._ema("rec_ms", (time.perf_counter() - t1) * 1000.0)

        visible = [t for t in self.tracker.tracks
                   if t.confirmed and t.time_since_update <= self.display_stale]

        now = time.perf_counter()
        if self._last_call is not None:
            inst = 1.0 / max(now - self._last_call, 1e-6)
            self.fps = inst if self.fps == 0 else 0.9 * self.fps + 0.1 * inst
        self._last_call = now
        self._ema("proc_ms", (now - t_start) * 1000.0)

        identified = [t.ident.student.name for t in visible
                      if t.ident and t.ident.status == "identified"]
        unknown = sum(1 for t in visible if t.ident and (t.ident.status == "unknown"
                      or (t.ident.status == "pending" and t.ident.ever_unknown)))
        info = {
            "fps": self.fps, "proc_ms": self.proc_ms, "det_ms": self.det_ms, "rec_ms": self.rec_ms,
            "ran_detect": ran_detect, "faces": len(visible), "identified": identified,
            "unknown": unknown, "new_events": new_events, "session_logged": self.session_logged,
            "provider": getattr(self.engine, "provider_label", "?"),
        }
        return self._draw(frame.copy(), visible, info), info

    def close(self) -> None:
        """Nothing is held open (DB connections are per-call); kept for a symmetric API."""

    # -------------------------------------------------------------- internals
    def _ema(self, attr: str, value: float, alpha: float = 0.1) -> None:
        cur = getattr(self, attr)
        setattr(self, attr, value if cur == 0 else (1 - alpha) * cur + alpha * value)

    def _maybe_reload_gallery(self) -> None:
        if time.monotonic() - self._gallery_checked < 2.0:
            return
        self._gallery_checked = time.monotonic()
        if self.store.gallery_version() != self.gallery.version:
            self.gallery = self.store.load_gallery()        # new enrolments appear live

    def _update_gate_crossing(self, tr: Track, w: int, h: int) -> None:
        s = self.s
        if not s.gate_line_enabled:
            return
        cx, cy = tr.center
        if s.gate_line_orientation == "horizontal":
            d, band = cy - s.gate_line_ratio * h, 0.015 * h
        else:
            d, band = cx - s.gate_line_ratio * w, 0.015 * w
        if abs(d) < band:                                    # hysteresis against jitter on the line
            return
        side = 1 if d > 0 else -1
        if tr.gate_side is not None and side != tr.gate_side:
            positive_is_entry = s.gate_entry_direction in ("down", "right")
            tr.last_direction = "ENTRY" if (side > 0) == positive_is_entry else "EXIT"
        tr.gate_side = side

    def _quality_sample(self, det: Detection, frame: np.ndarray, ident: Identity):
        """Return (aligned_crop, quality) if this detection is good enough to embed, else None."""
        s = self.s
        if det.kps is None:
            ident.hint = "no landmarks"; return None
        if det.score < s.min_det_score:
            ident.hint = "low confidence"; return None
        if float(det.bbox[2] - det.bbox[0]) < s.min_face_px:
            ident.hint = "too small"; return None
        ps = pose_score(det.kps)
        if ps < s.min_pose_score:
            ident.hint = "face the camera"; return None
        try:
            aligned, _ = align_face(frame, det.kps)
        except ValueError:
            ident.hint = "bad landmarks"; return None
        blur = laplacian_variance(aligned)
        ident.blur = blur
        if blur < s.min_blur_var:
            ident.hint = "blurry"; return None
        if s.liveness_mode == "fft_experimental" and fft_moire_score(aligned) < s.liveness_min_score:
            ident.spoof_votes += 1
            ident.hint = "possible spoof"
            if ident.spoof_votes >= 3 and not ident.embs:
                ident.status = "spoof"
            return None
        ident.hint = ""
        quality = float(np.clip(blur / 150.0, 0.1, 1.0) * ps)
        return aligned, quality

    def _recognize(self, tr: Track, frame: np.ndarray) -> Optional[str]:
        s = self.s
        if tr.ident is None:
            tr.ident = Identity(last_verify_frame=self.frame_idx)
        ident: Identity = tr.ident

        if ident.status in ("unknown", "spoof") and \
                self.frame_idx - ident.unknown_since >= s.unknown_retry_frames:
            self._reset(ident)                                # give a persistent unknown a fresh look

        if ident.status == "identified":
            if self.frame_idx - ident.last_verify_frame >= s.reverify_interval_frames:
                self._reverify(tr, frame)
            return self._try_log(tr) if ident.status == "identified" else None
        if ident.status in ("unknown", "spoof"):
            return None

        # ---- pending: collect a quality keyframe
        if self.frame_idx - ident.last_rec_frame < s.rec_interval_frames:
            return None
        sample = self._quality_sample(tr.last_det, frame, ident)
        if ident.status == "spoof":
            ident.unknown_since = self.frame_idx
            return None
        if sample is None:
            return None
        aligned, quality = sample
        ident.last_rec_frame = self.frame_idx
        emb = self.engine.embed_aligned(aligned)

        ident.embs.append(emb)
        ident.quals.append(quality)
        ident.attempts += 1
        single = self.gallery.match(emb)
        single_ok = Gallery.accept(single, s.similarity_threshold, s.similarity_margin)
        ident.votes.append(single.student.id if single_ok else -1)

        n = len(ident.embs)
        agg = l2_normalize(sum(q * e for q, e in zip(ident.quals, ident.embs)))
        m = self.gallery.match(agg)
        if Gallery.accept(m, s.similarity_threshold, s.similarity_margin):
            agree = sum(1 for v in ident.votes if v == m.student.id) / len(ident.votes)
            strong = (single_ok and single.similarity >= s.early_accept_sim
                      and single.student.id == m.student.id and n >= 2)
            if (n >= s.min_votes and agree >= 0.5) or strong:
                ident.status = "identified"
                ident.student, ident.similarity = m.student, m.similarity
                ident.mismatches = 0
                ident.last_verify_frame = self.frame_idx
                ident.hint = ""
                return self._try_log(tr)
        if ident.attempts >= s.max_attempts:
            ident.status = "unknown"
            ident.ever_unknown = True
            ident.unknown_since = self.frame_idx
        return None

    def _reverify(self, tr: Track, frame: np.ndarray) -> None:
        """Re-embed an identified track; two consecutive disagreements reset it (guards ID swaps)."""
        s, ident = self.s, tr.ident
        ident.last_verify_frame = self.frame_idx
        sample = self._quality_sample(tr.last_det, frame, ident)
        if sample is None:
            return
        m = self.gallery.match(self.engine.embed_aligned(sample[0]))
        same = (m is not None and m.student.id == ident.student.id
                and m.similarity >= 0.9 * s.similarity_threshold)
        ident.mismatches = 0 if same else ident.mismatches + 1
        if ident.mismatches >= 2:
            self._reset(ident)

    @staticmethod
    def _reset(ident: Identity) -> None:
        ident.status = "pending"
        ident.student = None
        ident.similarity = 0.0
        ident.embs.clear(); ident.quals.clear(); ident.votes.clear()
        ident.attempts = 0
        ident.mismatches = 0
        ident.spoof_votes = 0
        ident.hint = ""

    def _try_log(self, tr: Track) -> Optional[str]:
        s, ident = self.s, tr.ident
        if not self.log_attendance:
            return None
        if s.gate_line_enabled and s.require_gate_crossing and tr.last_direction is None:
            return None                                        # waiting for the line to be crossed
        direction = tr.last_direction or s.default_direction
        if self.logger.maybe_log(ident.student, ident.similarity, direction):
            msg = (f"{time.strftime('%H:%M:%S')}  {ident.student.name} "
                   f"({ident.student.roll_number}) - {direction}")
            self.events.appendleft(msg)
            self.session_logged += 1
            return msg
        return None

    # ---------------------------------------------------------------- drawing
    def _draw(self, canvas: np.ndarray, tracks: List[Track], info: Dict) -> np.ndarray:
        h, w = canvas.shape[:2]
        fs = float(np.clip(w / 1280.0, 0.45, 1.2))
        th = max(1, int(round(fs * 2)))

        if self.s.gate_line_enabled:
            if self.s.gate_line_orientation == "horizontal":
                y = int(self.s.gate_line_ratio * h)
                cv2.line(canvas, (0, y), (w, y), (0, 215, 255), th, cv2.LINE_AA)
            else:
                x = int(self.s.gate_line_ratio * w)
                cv2.line(canvas, (x, 0), (x, h), (0, 215, 255), th, cv2.LINE_AA)

        for tr in tracks:
            ident = tr.ident
            if ident and ident.status == "identified":
                color = GREEN
                label = f"{ascii_safe(ident.student.name)} ({ident.student.roll_number}) {ident.similarity:.2f}"
            elif ident and ident.status == "spoof":
                color, label = RED, "Possible spoof"
            elif ident and (ident.status == "unknown" or (ident.status == "pending" and ident.ever_unknown)):
                color, label = RED, "Unknown"
            else:
                color = AMBER
                label = "Verifying" + (f" ({ident.hint})" if ident and ident.hint else "...")

            x1, y1, x2, y2 = [int(v) for v in tr.bbox]
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, th + 1)
            if len(tr.history) > 1:
                pts = np.array(tr.history, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(canvas, [pts], False, color, max(1, th - 1), cv2.LINE_AA)
            (tw, tgh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55 * fs + 0.2, th)
            top = max(0, y1 - tgh - 10)
            cv2.rectangle(canvas, (x1, top), (x1 + tw + 8, top + tgh + 10), color, -1)
            cv2.putText(canvas, label, (x1 + 4, top + tgh + 3), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55 * fs + 0.2, DARK, th, cv2.LINE_AA)

        lines = [
            f"FPS {info['fps']:.1f} | detect {self.det_ms:.0f} ms | match {self.rec_ms:.0f} ms",
            f"Faces {info['faces']} | recognised {len(info['identified'])} | unknown {info['unknown']} "
            f"| logged {self.session_logged}",
            f"Engine: {info['provider']}",
        ]
        lh = int(26 * fs + 8)
        cv2.rectangle(canvas, (8, 8), (int(560 * fs + 80), 16 + lh * len(lines)), DARK, -1)
        for i, text in enumerate(lines):
            cv2.putText(canvas, text, (16, 8 + lh * (i + 1) - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5 * fs + 0.15, (120, 255, 150) if i == 0 else WHITE, 1, cv2.LINE_AA)
        return canvas
