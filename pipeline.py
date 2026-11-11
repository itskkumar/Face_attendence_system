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
  7. (Optional) Deferred recognition: tracks that leave the frame while pending
     are queued for background processing using buffered frame crops
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

import antispoof
import pad_store
from antispoof import PADProvider
from attendance import AttendanceLogger
from config import Settings
from database import Gallery, Store, StudentInfo
from snapshot_manager import save_snapshot
from tracker import ByteTrackLite, Detection, Track
from vision_math import align_face, compute_fft_liveness, fft_moire_score, l2_normalize, laplacian_variance, pose_score

log = logging.getLogger("pipeline")

GREEN = (113, 204, 46)     # BGR
RED = (60, 60, 230)
AMBER = (0, 190, 255)
DARK = (20, 20, 20)
WHITE = (255, 255, 255)
GREY = (170, 170, 170)
PURPLE = (200, 90, 170)


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
    # For deferred recognition (fast-moving persons)
    frame_crops: Deque[Tuple[np.ndarray, float]] = field(default_factory=lambda: deque(maxlen=5))  # (BGR crop, quality)
    best_aligned_face: Optional[np.ndarray] = None          # 112x112 aligned face for snapshot
    best_person_crop: Optional[np.ndarray] = None           # bounding box crop for snapshot
    # PAD (additive; only used when liveness_mode == "minifas")
    pad_obs: Deque[float] = field(default_factory=lambda: deque(maxlen=5))   # real-probabilities
    pad_state: str = antispoof.UNCERTAIN
    pad_real_mean: float = 0.0
    pad_last_spoof_prob: Optional[float] = None
    pad_last_frame: int = -10 ** 9
    pad_started_at: Optional[float] = None                  # monotonic time of the first observation
    pad_flagged_uncertain: bool = False
    pad_reason: str = ""
    pad_ms: float = 0.0
    pad_reject_reported: str = ""                          # last PAD state already reported as rejected
    pad_track_id: int = -1
    logged: bool = False                                    # attendance row written for this track


class GatePipeline:
    def __init__(self, engine, store: Store, settings: Settings, *, source_label: str = "live",
                 is_file: bool = False, logger: Optional[AttendanceLogger] = None,
                 log_attendance: bool = True, camera_label: str = "default",
                 pad: Optional[PADProvider] = None,
                 event_sink: Optional[Callable[[dict], None]] = None):
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
            tentative_max_age=max(4, 2 * self.detect_every),
            on_track_lost=self._on_track_lost if settings.enable_deferred_recognition else None)
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

        # Anti-spoofing (additive). `pad` is shared by the caller (one session per process).
        self.event_sink = event_sink
        self.pad_ms = 0.0
        self._pad_mode = settings.liveness_mode == "minifas"
        self.pad: Optional[PADProvider] = None
        if self._pad_mode:
            self.pad = pad if pad is not None else antispoof.NullPAD("no PAD provider supplied")
            with store._conn() as _c:
                pad_store.ensure_pad_schema(_c)

        # Deferred recognition (for fast-moving persons who leave the frame)
        self._deferred_queue: queue.Queue = queue.Queue(maxsize=50)
        self._deferred_results: Dict[int, str] = {}  # track_id -> result message
        self._deferred_stop = threading.Event()
        if settings.enable_deferred_recognition:
            self._deferred_thread = threading.Thread(target=self._deferred_worker, daemon=True,
                                                     name="deferred-recognition")
            self._deferred_thread.start()

    # ------------------------------------------------------------------ main
    def process(self, frame: np.ndarray) -> Tuple[np.ndarray, Dict]:
        t_start = time.perf_counter()
        self.frame_idx += 1
        self._maybe_reload_gallery()
        self.tracker.predict()

        new_events: List[str] = []

        # Check for deferred recognition results
        if self.s.enable_deferred_recognition:
            for track_id in list(self._deferred_results.keys()):
                msg = self._deferred_results.pop(track_id)
                new_events.append(msg)
                self.events.appendleft(msg)
                self.session_logged += 1

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
            "liveness_mode": self.s.liveness_mode, "pad_ms": self.pad_ms,
            "tracks": self.track_details(visible),
        }
        return self._draw(frame.copy(), visible, info), info

    def close(self) -> None:
        """Stop deferred worker and clean up resources."""
        if self.s.enable_deferred_recognition:
            self._deferred_stop.set()
            self._deferred_queue.put(None)  # wake up the worker
            self._deferred_thread.join(timeout=2.0)

    # -------------------------------------------------------------- deferred recognition
    def _on_track_lost(self, track: Track) -> None:
        """Called when a track is about to be removed from the tracker."""
        if not track.ident or track.ident.status != "pending":
            return
        if self._pad_mode and track.ident.pad_state != antispoof.LIVE:
            # A track that never passed PAD must not be identified/logged after it leaves the frame.
            self._emit("attendance.rejected", track.id, track.ident, reason="left frame without LIVE (deferred path blocked)")
            return
        # Only queue if we have some embeddings to work with
        if len(track.ident.embs) >= self.s.deferred_min_embeddings:
            try:
                self._deferred_queue.put_nowait((track.id, track.ident, track.last_direction))
            except queue.Full:
                pass  # Queue full, drop this one

    def _deferred_worker(self) -> None:
        """Background thread that processes tracks that left the frame while pending."""
        while not self._deferred_stop.is_set():
            try:
                item = self._deferred_queue.get(timeout=0.5)
                if item is None:  # Shutdown signal
                    break
                track_id, ident, direction = item

                # Process buffered frame crops if available
                if ident.frame_crops:
                    for crop, quality in ident.frame_crops:
                        try:
                            # Re-embed from buffered crops
                            emb = self.engine.embed_aligned(crop)
                            ident.embs.append(emb)
                            ident.quals.append(quality)

                            single = self.gallery.match(emb)
                            single_ok = Gallery.accept(single, self.s.similarity_threshold,
                                                      self.s.similarity_margin)
                            ident.votes.append(single.student.id if single_ok else -1)
                        except Exception:
                            log.exception("deferred recognition: could not embed a buffered crop")
                            continue

                # Aggregate and try to identify
                if len(ident.embs) >= self.s.min_votes:
                    agg = l2_normalize(sum(q * e for q, e in zip(ident.quals, ident.embs)))
                    m = self.gallery.match(agg)
                    if Gallery.accept(m, self.s.similarity_threshold, self.s.similarity_margin):
                        agree = sum(1 for v in ident.votes if v == m.student.id) / len(ident.votes)
                        if agree >= 0.5:
                            ident.status = "identified"
                            ident.student, ident.similarity = m.student, m.similarity

                            # Try to log attendance
                            if self.log_attendance:
                                logged = self._log_deferred(ident, direction or self.s.default_direction)
                                if logged:
                                    msg = (f"{time.strftime('%H:%M:%S')} [DEFERRED] {ident.student.name} "
                                          f"({ident.student.roll_number}) - identified after leaving frame")
                                    self._deferred_results[track_id] = msg

            except queue.Empty:
                continue
            except Exception:
                log.exception("deferred recognition worker error")

    def _log_deferred(self, ident: Identity, direction: str) -> bool:
        """Log attendance for deferred identification (no snapshots available)."""
        if not self.log_attendance or not ident.student:
            return False
        if self._pad_mode and ident.pad_state != antispoof.LIVE:
            return False                                      # PAD gate: no attendance without LIVE
        logged = self.logger.maybe_log(ident.student, ident.similarity, direction)
        if logged:
            ident.logged = True
            self._after_logged(ident.pad_track_id, ident)
        return logged

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

    def _quality_sample(self, det: Detection, frame: np.ndarray, ident: Identity, bbox: np.ndarray):
        """Return (aligned_crop, quality, person_crop) if this detection is good enough to embed, else None."""
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
        if self._pad_mode:
            self._pad_observe(det, frame, ident, bbox)
            if ident.status == "spoof":
                return None
        ident.hint = ""
        quality = float(np.clip(blur / 150.0, 0.1, 1.0) * ps)

        # Extract person crop from bounding box
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        person_crop = frame[y1:y2, x1:x2].copy()

        return aligned, quality, person_crop

    def _recognize(self, tr: Track, frame: np.ndarray) -> Optional[str]:
        s = self.s
        if tr.ident is None:
            tr.ident = Identity(last_verify_frame=self.frame_idx)
            tr.ident.pad_track_id = tr.id
            self._emit("face.detected", tr.id, tr.ident, det_score=float(tr.last_det.score))
        ident: Identity = tr.ident

        if ident.status in ("unknown", "spoof") and \
                self.frame_idx - ident.unknown_since >= s.unknown_retry_frames:
            self._reset(ident)                                # give a persistent unknown a fresh look

        if ident.status == "identified":
            if self.frame_idx - ident.last_verify_frame >= s.reverify_interval_frames:
                self._reverify(tr, frame)
            elif self._pad_mode and ident.pad_state != antispoof.LIVE:
                # identity locked but liveness not yet proven: keep collecting PAD observations
                self._quality_sample(tr.last_det, frame, ident, tr.bbox)
            return self._try_log(tr) if ident.status == "identified" else None
        if ident.status in ("unknown", "spoof"):
            return None

        # ---- pending: collect a quality keyframe
        if self.frame_idx - ident.last_rec_frame < s.rec_interval_frames:
            return None
        sample = self._quality_sample(tr.last_det, frame, ident, tr.bbox)
        if ident.status == "spoof":
            ident.unknown_since = self.frame_idx
            return None
        if sample is None:
            return None
        aligned, quality, person_crop = sample
        ident.last_rec_frame = self.frame_idx
        emb = self.engine.embed_aligned(aligned)

        # Buffer crops for deferred recognition
        if s.enable_deferred_recognition and len(ident.frame_crops) < s.buffer_crops_for_deferred:
            ident.frame_crops.append((aligned.copy(), quality))

        # Keep track of best crops for snapshots
        if ident.best_aligned_face is None or quality > max(ident.quals, default=0):
            ident.best_aligned_face = aligned.copy()
            ident.best_person_crop = person_crop.copy()

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
                self._emit("identity.verified", tr.id, ident, similarity=float(ident.similarity))
                return self._try_log(tr)
        if ident.attempts >= s.max_attempts:
            ident.status = "unknown"
            ident.ever_unknown = True
            ident.unknown_since = self.frame_idx
            self._emit("identity.unknown", tr.id, ident)
        return None

    def _reverify(self, tr: Track, frame: np.ndarray) -> None:
        """Re-embed an identified track; two consecutive disagreements reset it (guards ID swaps)."""
        s, ident = self.s, tr.ident
        ident.last_verify_frame = self.frame_idx
        sample = self._quality_sample(tr.last_det, frame, ident, tr.bbox)
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
        ident.pad_obs.clear()                                 # PAD evidence never survives an identity reset
        ident.pad_state = antispoof.UNCERTAIN
        ident.pad_real_mean = 0.0
        ident.pad_started_at = None
        ident.pad_last_frame = -10 ** 9
        ident.pad_flagged_uncertain = False
        ident.pad_reject_reported = ""
        ident.logged = False

    def _try_log(self, tr: Track) -> Optional[str]:
        s, ident = self.s, tr.ident
        if not self.log_attendance:
            return None
        if self._pad_mode and ident.pad_state != antispoof.LIVE:
            self._pad_withhold(tr)                              # PAD gate: identity may lock, attendance may not
            return None
        if s.gate_line_enabled and s.require_gate_crossing and tr.last_direction is None:
            return None                                        # waiting for the line to be crossed
        direction = tr.last_direction or s.default_direction

        # Save snapshots if enabled
        face_snapshot_path = None
        person_snapshot_path = None
        if s.save_snapshots and ident.best_aligned_face is not None:
            now = datetime.now()
            try:
                face_snapshot_path = save_snapshot(ident.best_aligned_face, ident.student.roll_number,
                                                  now, kind="face")
                if ident.best_person_crop is not None:
                    person_snapshot_path = save_snapshot(ident.best_person_crop, ident.student.roll_number,
                                                        now, kind="person")
            except Exception as e:
                # Don't fail attendance logging if snapshot save fails
                pass

        if self.logger.maybe_log(ident.student, ident.similarity, direction,
                                face_snapshot=face_snapshot_path, person_snapshot=person_snapshot_path):
            msg = (f"{time.strftime('%H:%M:%S')}  {ident.student.name} "
                   f"({ident.student.roll_number}) - {direction}")
            self.events.appendleft(msg)
            self.session_logged += 1
            ident.logged = True
            self._after_logged(tr.id, ident)
            return msg
        return None

    # ---------------------------------------------------------------- PAD / events (additive hooks)
    def _emit(self, etype: str, track_id: int, ident: Identity, **extra) -> None:
        """Typed event for the optional event_sink. Never carries embeddings."""
        if self.event_sink is None:
            return
        ev = {"event_id": uuid.uuid4().hex, "type": etype, "ts": datetime.now().isoformat(timespec="milliseconds"),
              "camera_id": self.camera_label, "track_id": int(track_id), "status": ident.status,
              "pad_state": ident.pad_state if self._pad_mode else None,
              "pad_real_prob": round(ident.pad_real_mean, 4) if self._pad_mode else None,
              "liveness_mode": self.s.liveness_mode}
        if ident.student is not None:
            ev["student"] = {"roll_number": ident.student.roll_number, "name": ident.student.name}
        ev.update(extra)
        try:
            self.event_sink(ev)
        except Exception:
            log.exception("event_sink raised")

    def _after_logged(self, track_id: int, ident: Identity) -> None:
        if self._pad_mode:
            pad_store.annotate_attendance(self.store.path, ident.student.roll_number, ident.pad_state,
                                          ident.pad_real_mean)
        self._emit("attendance.recorded", track_id, ident, similarity=float(ident.similarity))

    def _pad_withhold(self, tr: Track) -> None:
        ident = tr.ident
        if ident.pad_reject_reported == ident.pad_state:
            return
        ident.pad_reject_reported = ident.pad_state
        policy = self.s.pad_unconfigured_policy
        if ident.pad_state in (antispoof.NOT_CONFIGURED, antispoof.ERROR):
            reason = f"PAD {ident.pad_state.lower()}: {ident.pad_reason}"
            self._emit("attendance.rejected" if policy == "reject" else "review.required", tr.id, ident,
                       reason=reason, policy=policy)
        elif ident.pad_state == antispoof.SPOOF:
            self._emit("attendance.rejected", tr.id, ident, reason="spoof")
        else:
            self._emit("attendance.rejected", tr.id, ident, reason="liveness not yet confirmed (will retry while the face is visible)")

    def _pad_observe(self, det: Detection, frame: np.ndarray, ident: Identity, bbox: np.ndarray) -> None:
        """Run PAD on this detection (candidate frames only), update the per-track decision."""
        s = self.s
        if self.frame_idx - ident.pad_last_frame < s.pad_observation_interval_frames:
            return
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in det.bbox]
        m = s.pad_edge_margin_px
        if x1 <= m or y1 <= m or x2 >= w - 1 - m or y2 >= h - 1 - m:
            ident.pad_reason = "face at frame edge"
            return                                              # no observation: never counted as live
        ident.pad_last_frame = self.frame_idx
        if ident.pad_started_at is None:
            ident.pad_started_at = time.monotonic()
            self._emit("liveness.started", ident.pad_track_id, ident)
        res = self.pad.observe(frame, det.bbox)
        self._ema("pad_ms", res.latency_ms)
        ident.pad_ms = res.latency_ms
        if not res.valid:                                       # NOT_CONFIGURED / ERROR: no score, no LIVE
            ident.pad_state, ident.pad_reason = res.state, res.reason
            return
        ident.pad_obs.append(res.real_prob)
        prev = ident.pad_state
        state, mean = antispoof.decide_pad(ident.pad_obs, min_obs=s.pad_min_obs,
                                           real_threshold=s.pad_real_threshold,
                                           spoof_threshold=s.pad_spoof_threshold)
        ident.pad_state, ident.pad_real_mean, ident.pad_reason = state, mean, ""
        ident.pad_last_spoof_prob = 1.0 - mean
        tid = ident.pad_track_id
        if state == antispoof.LIVE and prev != antispoof.LIVE:
            self._pad_record(tid, ident, res)
            self._emit("liveness.passed", tid, ident)
        elif state == antispoof.SPOOF:
            was_identified = ident.student is not None
            if prev != antispoof.SPOOF:
                self._pad_record(tid, ident, res, flagged=True,
                                 note="spoof after identification" if was_identified else "spoof")
                self._emit("liveness.failed", tid, ident, after_identification=was_identified)
                if was_identified:
                    try:
                        self.store.log_audit("system", "pad_spoof_after_identification",
                                             f"camera={self.camera_label} track={tid} "
                                             f"student={ident.student.roll_number} real_mean={mean:.3f}")
                    except Exception:
                        log.exception("could not write PAD audit entry")
            ident.status = "spoof"                              # stops further logging for this track
            ident.unknown_since = self.frame_idx
        elif state == antispoof.UNCERTAIN and not ident.pad_flagged_uncertain and ident.pad_started_at is not None \
                and time.monotonic() - ident.pad_started_at > s.pad_max_observation_seconds:
            ident.pad_flagged_uncertain = True
            self._pad_record(tid, ident, res, flagged=True, note="review required: liveness not confirmed in time")
            self._emit("liveness.uncertain", tid, ident)

    def _pad_record(self, track_id: int, ident: Identity, res, flagged: bool = False, note: str = "") -> None:
        pad_store.record_pad_event(
            self.store.path, camera_label=self.camera_label, track_id=track_id, state=ident.pad_state,
            real_prob=ident.pad_real_mean, spoof_prob=1.0 - ident.pad_real_mean, model_id=res.model_id,
            student_id=ident.student.id if ident.student is not None else None, flagged=flagged, note=note)

    def ui_status(self, tr: Track) -> str:
        """Label for the UI (see the React live page)."""
        ident = tr.ident
        if ident is None:
            return "DETECTED"
        if ident.status == "spoof":
            return "POSSIBLE SPOOF"
        if ident.status == "unknown" or (ident.status == "pending" and ident.ever_unknown):
            return "UNKNOWN"
        if ident.status == "identified":
            if self._pad_mode and ident.pad_state != antispoof.LIVE:
                if ident.pad_state in (antispoof.NOT_CONFIGURED, antispoof.ERROR):
                    return "PAD NOT CONFIGURED"
                if ident.pad_flagged_uncertain:
                    return "REVIEW REQUIRED"
                return "CHECKING LIVENESS"
            return "ATTENDANCE RECORDED" if ident.logged else "VERIFIED"
        if self._pad_mode and ident.pad_state in (antispoof.NOT_CONFIGURED, antispoof.ERROR):
            return "PAD NOT CONFIGURED"
        if self._pad_mode and ident.pad_obs and not ident.embs:
            return "CHECKING LIVENESS"
        return "VERIFYING IDENTITY" if ident.embs else "TRACKING"

    def track_details(self, tracks: List[Track]) -> List[dict]:
        """JSON-safe per-track info for the UI. Never contains embeddings."""
        out = []
        for tr in tracks:
            ident = tr.ident
            out.append({
                "track_id": int(tr.id), "bbox": [float(v) for v in tr.bbox],
                "status": self.ui_status(tr),
                "name": ident.student.name if ident and ident.student else None,
                "roll_number": ident.student.roll_number if ident and ident.student else None,
                "det_score": float(tr.last_det.score) if tr.last_det is not None else None,
                "similarity": float(ident.similarity) if ident and ident.student else None,
                "pad_state": ident.pad_state if (ident and self._pad_mode) else None,
                "pad_real_prob": float(ident.pad_real_mean) if (ident and self._pad_mode and ident.pad_obs) else None,
                "hint": ident.hint if ident else "",
            })
        return out

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

            if self._pad_mode and ident:
                ui = self.ui_status(tr)
                if ui in ("CHECKING LIVENESS", "REVIEW REQUIRED", "PAD NOT CONFIGURED", "POSSIBLE SPOOF"):
                    color = {"CHECKING LIVENESS": PURPLE, "REVIEW REQUIRED": GREY, "PAD NOT CONFIGURED": GREY,
                             "POSSIBLE SPOOF": RED}[ui]
                    who = f"{ascii_safe(ident.student.name)} - " if ident.student else ""
                    label = who + ui.title() if ui != "POSSIBLE SPOOF" else "Possible spoof"
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
            f"Engine: {info['provider']}" + (f" | PAD {self.pad_ms:.0f} ms" if self._pad_mode else
                                              " | Anti-spoofing OFF" if self.s.liveness_mode == "off" else ""),
        ]
        lh = int(26 * fs + 8)
        cv2.rectangle(canvas, (8, 8), (int(560 * fs + 80), 16 + lh * len(lines)), DARK, -1)
        for i, text in enumerate(lines):
            cv2.putText(canvas, text, (16, 8 + lh * (i + 1) - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5 * fs + 0.15, (120, 255, 150) if i == 0 else WHITE, 1, cv2.LINE_AA)
        return canvas
