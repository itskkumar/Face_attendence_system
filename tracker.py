"""
tracker.py - multi-face tracking (ByteTrack-style, pure NumPy/SciPy).

Why track at all?  Without tracking, every processed frame would re-run the
expensive ArcFace model for every face and an identity could flicker. With
tracking, each person gets a persistent id, ArcFace runs only on a few
quality keyframes per person, and the box keeps moving smoothly (predicted by
the Kalman filter) on frames where the detector is skipped.

Components
  * KalmanFilterXYAH : constant-velocity filter on (cx, cy, aspect, height); the
                       noise scales with box height, which is what makes it
                       behave across near and far faces (DeepSORT formulation).
  * Two-stage association (ByteTrack): high-confidence detections are matched
    first (IoU cost + Mahalanobis gating, Hungarian assignment); remaining
    tracks then get a second chance against LOW-confidence detections, which
    recovers faces that are briefly blurred or partly occluded.
"""
from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import scipy.linalg
from scipy.optimize import linear_sum_assignment

_BIG = 1e5


@dataclass
class Detection:
    bbox: np.ndarray                 # xyxy, original-frame pixels
    kps: Optional[np.ndarray]        # (5, 2) landmarks, original-frame pixels
    score: float


def xyxy_to_xyah(b) -> np.ndarray:
    w, h = float(b[2] - b[0]), float(b[3] - b[1])
    h = max(h, 1e-3)
    return np.array([b[0] + w / 2.0, b[1] + h / 2.0, w / h, h], dtype=np.float64)


def xyah_to_xyxy(m) -> np.ndarray:
    h = max(float(m[3]), 1e-3)
    w = float(m[2]) * h
    return np.array([m[0] - w / 2.0, m[1] - h / 2.0, m[0] + w / 2.0, m[1] + h / 2.0], dtype=np.float64)


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU between (M,4) and (N,4) xyxy boxes."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float64)
    a = a[:, None, :]
    b = b[None, :, :]
    iw = np.maximum(0.0, np.minimum(a[..., 2], b[..., 2]) - np.maximum(a[..., 0], b[..., 0]))
    ih = np.maximum(0.0, np.minimum(a[..., 3], b[..., 3]) - np.maximum(a[..., 1], b[..., 1]))
    inter = iw * ih
    area_a = (a[..., 2] - a[..., 0]) * (a[..., 3] - a[..., 1])
    area_b = (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])
    return inter / np.maximum(area_a + area_b - inter, 1e-9)


class KalmanFilterXYAH:
    """State x = [cx, cy, a, h, vcx, vcy, va, vh];  measurement z = [cx, cy, a, h]."""

    def __init__(self):
        ndim, dt = 4, 1.0
        self._F = np.eye(2 * ndim)
        for i in range(ndim):
            self._F[i, ndim + i] = dt
        self._H = np.eye(ndim, 2 * ndim)
        self._w_pos = 1.0 / 20
        self._w_vel = 1.0 / 160

    def initiate(self, z: np.ndarray):
        mean = np.r_[z, np.zeros(4)]
        h = z[3]
        std = [2 * self._w_pos * h, 2 * self._w_pos * h, 1e-2, 2 * self._w_pos * h,
               10 * self._w_vel * h, 10 * self._w_vel * h, 1e-5, 10 * self._w_vel * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean: np.ndarray, cov: np.ndarray):
        h = max(float(mean[3]), 1.0)
        std_pos = [self._w_pos * h, self._w_pos * h, 1e-2, self._w_pos * h]
        std_vel = [self._w_vel * h, self._w_vel * h, 1e-5, self._w_vel * h]
        Q = np.diag(np.square(np.r_[std_pos, std_vel]))
        mean = self._F @ mean
        cov = self._F @ cov @ self._F.T + Q
        return mean, cov

    def project(self, mean: np.ndarray, cov: np.ndarray):
        h = max(float(mean[3]), 1.0)
        std = [self._w_pos * h, self._w_pos * h, 1e-1, self._w_pos * h]
        R = np.diag(np.square(std))
        return self._H @ mean, self._H @ cov @ self._H.T + R

    def update(self, mean: np.ndarray, cov: np.ndarray, z: np.ndarray):
        pm, pc = self.project(mean, cov)
        chol, lower = scipy.linalg.cho_factor(pc, lower=True, check_finite=False)
        gain = scipy.linalg.cho_solve((chol, lower), (cov @ self._H.T).T, check_finite=False).T
        new_mean = mean + (z - pm) @ gain.T
        new_cov = cov - gain @ pc @ gain.T
        return new_mean, new_cov

    def gating_distance(self, mean: np.ndarray, cov: np.ndarray, measurements: np.ndarray) -> np.ndarray:
        """Squared Mahalanobis distance of each measurement from the projected state."""
        pm, pc = self.project(mean, cov)
        L = np.linalg.cholesky(pc)
        d = measurements - pm
        z = scipy.linalg.solve_triangular(L, d.T, lower=True, check_finite=False)
        return np.sum(z * z, axis=0)


class Track:
    def __init__(self, track_id: int, det: Detection, kf: KalmanFilterXYAH, frame_idx: int):
        self.id = track_id
        self.kf = kf
        self.mean, self.cov = kf.initiate(xyxy_to_xyah(det.bbox))
        self.hits = 1
        self.age = 0
        self.time_since_update = 0
        self.confirmed = False
        self.last_det: Detection = det
        self.born_frame = frame_idx
        self.history: deque = deque(maxlen=40)       # recent centres for the trail
        self.history.append(self.center)
        # filled in by the pipeline
        self.ident = None
        self.gate_side: Optional[int] = None
        self.last_direction: Optional[str] = None

    @property
    def bbox(self) -> np.ndarray:
        return xyah_to_xyxy(self.mean)

    @property
    def center(self) -> Tuple[float, float]:
        return float(self.mean[0]), float(self.mean[1])

    def predict(self) -> None:
        if self.time_since_update > 0:
            self.mean[7] = 0.0           # a lost face should not keep growing/shrinking
        self.mean, self.cov = self.kf.predict(self.mean, self.cov)
        self.age += 1
        self.time_since_update += 1

    def update(self, det: Detection) -> None:
        self.mean, self.cov = self.kf.update(self.mean, self.cov, xyxy_to_xyah(det.bbox))
        self.hits += 1
        self.time_since_update = 0
        self.last_det = det
        self.history.append(self.center)


class ByteTrackLite:
    def __init__(self, high_thresh=0.5, low_thresh=0.1, new_thresh=0.6, match_thresh=0.8,
                 low_match_thresh=0.5, max_age=30, min_hits=2, tentative_max_age=4,
                 gating_thresh=13.28):
        self.high_thresh, self.low_thresh, self.new_thresh = high_thresh, low_thresh, new_thresh
        self.match_thresh, self.low_match_thresh = match_thresh, low_match_thresh
        self.max_age, self.min_hits, self.tentative_max_age = max_age, min_hits, tentative_max_age
        self.gating_thresh = gating_thresh        # chi-square 99% for 4 degrees of freedom
        self.kf = KalmanFilterXYAH()
        self.tracks: List[Track] = []
        self._ids = itertools.count(1)
        self.frame_idx = 0

    def predict(self) -> None:
        self.frame_idx += 1
        for t in self.tracks:
            t.predict()

    def _associate(self, tracks: List[Track], dets: List[Detection], thresh: float, gate: bool):
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))
        tb = np.array([t.bbox for t in tracks])
        db = np.array([d.bbox for d in dets])
        cost = 1.0 - iou_matrix(tb, db)
        if gate:
            meas = np.array([xyxy_to_xyah(b) for b in db])
            for i, t in enumerate(tracks):
                g = self.kf.gating_distance(t.mean, t.cov, meas)
                cost[i, g > self.gating_thresh] = _BIG
        cost = np.where(cost > thresh, _BIG, cost)
        rows, cols = linear_sum_assignment(cost)
        matches, ut, ud = [], set(range(len(tracks))), set(range(len(dets)))
        for r, c in zip(rows, cols):
            if cost[r, c] < _BIG:
                matches.append((r, c)); ut.discard(r); ud.discard(c)
        return matches, sorted(ut), sorted(ud)

    def update(self, detections: List[Detection]) -> List[Track]:
        """Associate this frame's detections; call predict() first on every frame."""
        high = [d for d in detections if d.score >= self.high_thresh]
        low = [d for d in detections if self.low_thresh <= d.score < self.high_thresh]

        m1, unmatched_tracks, unmatched_high = self._associate(self.tracks, high, self.match_thresh, True)
        for ti, di in m1:
            self.tracks[ti].update(high[di])

        remaining = [self.tracks[i] for i in unmatched_tracks if self.tracks[i].confirmed]
        m2, _, _ = self._associate(remaining, low, self.low_match_thresh, False)
        for ti, di in m2:
            remaining[ti].update(low[di])

        for di in unmatched_high:
            if high[di].score >= self.new_thresh:
                self.tracks.append(Track(next(self._ids), high[di], self.kf, self.frame_idx))

        for t in self.tracks:
            if t.hits >= self.min_hits:
                t.confirmed = True
        self.tracks = [
            t for t in self.tracks
            if not (t.time_since_update > self.max_age
                    or (not t.confirmed and t.time_since_update > self.tentative_max_age))
        ]
        return self.tracks
