"""
antispoof.py - presentation-attack detection (PAD), independent of recognition.

ArcFace answers WHO this is. PAD answers WHETHER A REAL FACE IS PRESENT. Attendance in
liveness_mode="minifas" requires both.

Provider states
  LIVE            real face (per-frame: real_prob >= pad_real_threshold; per-track: see decide_pad)
  SPOOF           clear attack evidence
  UNCERTAIN       anything else: too few observations, mixed evidence, face too small / at frame edge
  NOT_CONFIGURED  no validated weights installed (never a score, never LIVE)
  ERROR           weights present but failed validation / inference (reason says why)

There is no neutral fallback score anywhere in this module. Unavailable is reported as unavailable.

Model: Silent-Face-Anti-Spoofing (minivision-ai) MiniFASNetV2 (crop scale 2.7) and MiniFASNetV1SE
(crop scale 4.0), 80x80 input. Weights are NOT bundled; see data/models/antispoofing/MODELS.json and
tools/convert_minifas.py. The preprocessing below follows the official crop (CropImage._get_new_box)
as recorded in the manifest; it must be re-checked against the official source when weights are
installed (the author of this module had no network access when writing it).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from config import ANTISPOOFING_MODEL_DIR

LIVE = "LIVE"
SPOOF = "SPOOF"
UNCERTAIN = "UNCERTAIN"
NOT_CONFIGURED = "NOT_CONFIGURED"
ERROR = "ERROR"
PAD_STATES = (LIVE, SPOOF, UNCERTAIN, NOT_CONFIGURED, ERROR)

MANIFEST_NAME = "MODELS.json"
INPUT_SIZE = 80


@dataclass(frozen=True)
class PADResult:
    state: str
    real_prob: Optional[float] = None
    spoof_prob: Optional[float] = None
    model_id: str = ""
    latency_ms: float = 0.0
    reason: str = ""

    @property
    def valid(self) -> bool:
        """True when the result carries a real model score (usable as a temporal observation)."""
        return self.real_prob is not None and self.state in (LIVE, SPOOF, UNCERTAIN)


# ----------------------------------------------------------------------------- preprocessing
def expand_bbox(src_w: int, src_h: int, bbox_xywh: Sequence[float], scale: float) -> Tuple[int, int, int, int]:
    """Official Silent-Face crop box: scale around the centre, SHIFT (never squash) to stay in frame."""
    x, y, bw, bh = [float(v) for v in bbox_xywh]
    scale = min((src_h - 1) / bh, (src_w - 1) / bw, scale)
    nw, nh = bw * scale, bh * scale
    cx, cy = bw / 2 + x, bh / 2 + y
    lx, ly = cx - nw / 2, cy - nh / 2
    rx, ry = cx + nw / 2, cy + nh / 2
    if lx < 0:
        rx -= lx
        lx = 0
    if ly < 0:
        ry -= ly
        ly = 0
    if rx > src_w - 1:
        lx -= rx - src_w + 1
        rx = src_w - 1
    if ry > src_h - 1:
        ly -= ry - src_h + 1
        ry = src_h - 1
    return int(lx), int(ly), int(rx), int(ry)


def preprocess(frame_bgr: np.ndarray, bbox_xyxy: Sequence[float], scale: float,
               size: int = INPUT_SIZE) -> np.ndarray:
    """Frame + SCRFD box -> (1, 3, size, size) float32 tensor, BGR order, values 0..255 (NOT /255)."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox_xyxy]
    bw, bh = x2 - x1, y2 - y1
    if bw < 2 or bh < 2:
        raise ValueError("degenerate face box")
    lx, ly, rx, ry = expand_bbox(w, h, (x1, y1, bw, bh), scale)
    crop = frame_bgr[ly:ry + 1, lx:rx + 1]
    if crop.size == 0:
        raise ValueError("empty crop")
    crop = cv2.resize(crop, (size, size))
    return np.ascontiguousarray(crop.transpose(2, 0, 1)[None].astype(np.float32))


# ----------------------------------------------------------------------------- temporal decision
def decide_pad(real_probs: Sequence[float], *, min_obs: int, real_threshold: float,
               spoof_threshold: float, min_fraction: float = 0.6) -> Tuple[str, float]:
    """Per-track decision from the recent real-probabilities. Returns (state, mean_real_prob).

    LIVE needs >= min_obs observations, mean real_prob >= real_threshold AND at least `min_fraction`
    of the individual observations >= real_threshold. SPOOF is the mirror image. Everything else,
    including too little evidence, is UNCERTAIN and is never treated as live."""
    n = len(real_probs)
    if n == 0:
        return UNCERTAIN, 0.0
    arr = np.asarray(real_probs, dtype=np.float64)
    mean = float(arr.mean())
    if n < min_obs:
        return UNCERTAIN, mean
    if mean >= real_threshold and float((arr >= real_threshold).mean()) >= min_fraction:
        return LIVE, mean
    attack_cut = 1.0 - spoof_threshold
    if (1.0 - mean) >= spoof_threshold and float((arr <= attack_cut).mean()) >= min_fraction:
        return SPOOF, mean
    return UNCERTAIN, mean


# ----------------------------------------------------------------------------- providers
class PADProvider(ABC):
    model_id: str = ""

    @abstractmethod
    def observe(self, frame_bgr: np.ndarray, bbox_xyxy: Sequence[float]) -> PADResult:
        """One per-frame observation for one face."""

    @abstractmethod
    def health(self) -> Dict:
        """{'state': READY|NOT_CONFIGURED|ERROR, 'reason': str, 'model_id': str, ...} for the UI."""


class NullPAD(PADProvider):
    """Reports NOT_CONFIGURED. Used when no validated weights exist."""

    def __init__(self, reason: str = "no PAD weights installed"):
        self.reason = reason
        self.model_id = "none"

    def observe(self, frame_bgr, bbox_xyxy) -> PADResult:
        return PADResult(NOT_CONFIGURED, model_id=self.model_id, reason=self.reason)

    def health(self) -> Dict:
        return {"state": NOT_CONFIGURED, "reason": self.reason, "model_id": self.model_id, "models": []}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_html(path: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(512).lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or b"<head" in head


class MiniFASNetPAD(PADProvider):
    """ONNX Runtime MiniFASNet ensemble. One session per model per process.

    Construction never raises: any validation failure leaves the provider in NOT_CONFIGURED (nothing
    installed) or ERROR (installed but invalid) with the reason recorded, and observe() then returns
    that state instead of a score."""

    def __init__(self, model_dir: str = ANTISPOOFING_MODEL_DIR, *, real_threshold: float = 0.70,
                 spoof_threshold: float = 0.70, provider_label: Optional[str] = None):
        self.model_dir = model_dir
        self.real_threshold = real_threshold
        self.spoof_threshold = spoof_threshold
        self._models: List[dict] = []          # {id, session, input_name, scale, real_index}
        self._state = NOT_CONFIGURED
        self._reason = ""
        self.provider_label = ""
        self.model_id = "none"
        self._load(provider_label or os.environ.get("PAD_PROVIDER", "cpu"))

    # ---- loading + validation
    def _fail(self, state: str, reason: str) -> None:
        self._models, self._state, self._reason, self.model_id = [], state, reason, "none"

    def _load(self, provider_label: str) -> None:
        manifest_path = os.path.join(self.model_dir, MANIFEST_NAME)
        if not os.path.isfile(manifest_path):
            return self._fail(NOT_CONFIGURED, f"{MANIFEST_NAME} not found in {self.model_dir}")
        try:
            manifest = json.load(open(manifest_path))
            entries = manifest["models"]
            assert entries
        except Exception as exc:
            return self._fail(ERROR, f"unreadable {MANIFEST_NAME}: {exc}")

        present = [e for e in entries if os.path.exists(os.path.join(self.model_dir, e.get("file", "")))]
        if not present:
            return self._fail(NOT_CONFIGURED, "no model files installed (see MODELS.json / tools/convert_minifas.py)")
        if len(present) != len(entries):
            missing = [e["file"] for e in entries if e not in present]
            return self._fail(ERROR, f"model file(s) missing: {missing}")

        try:
            import onnxruntime as ort
            providers = self._providers(ort, provider_label)
        except Exception as exc:
            return self._fail(ERROR, f"onnxruntime unavailable: {exc}")

        loaded = []
        for e in entries:
            path = os.path.join(self.model_dir, e["file"])
            try:
                if _looks_like_html(path):
                    return self._fail(ERROR, f"{e['file']} is an HTML page, not an ONNX model")
                expected = e.get("sha256")
                if not expected:
                    return self._fail(ERROR, f"{e['file']}: manifest has no sha256 pinned "
                                             f"(run tools/convert_minifas.py or fill it in after verifying the file)")
                actual = _sha256(path)
                if actual.lower() != str(expected).lower():
                    return self._fail(ERROR, f"{e['file']}: sha256 mismatch (manifest {expected[:12]}..., file {actual[:12]}...)")
                sess = ort.InferenceSession(path, providers=providers)
                inp, out = sess.get_inputs()[0], sess.get_outputs()[0]
                size = e["input"]["size"]
                if list(inp.shape[1:]) != [3, size[0], size[1]] or inp.shape[0] not in (1, "batch", "N", None):
                    return self._fail(ERROR, f"{e['file']}: input shape {inp.shape} does not match manifest {size}")
                if out.shape[-1] != e["output"]["classes"]:
                    return self._fail(ERROR, f"{e['file']}: output shape {out.shape} does not match manifest")
                probe = sess.run(None, {inp.name: np.zeros((1, 3, size[0], size[1]), np.float32)})[0]
                if probe.shape != (1, e["output"]["classes"]) or not np.isfinite(probe).all() \
                        or abs(float(probe.sum()) - 1.0) > 1e-3:
                    return self._fail(ERROR, f"{e['file']}: dummy run gave non-softmax output {probe.tolist()}")
                loaded.append({"id": e["file"], "session": sess, "input_name": inp.name,
                               "scale": float(e["crop_scale"]), "size": int(size[0]),
                               "real_index": int(e["output"]["real_index"])})
            except Exception as exc:
                return self._fail(ERROR, f"{e['file']}: {type(exc).__name__}: {exc}")
        self._models, self._state, self._reason = loaded, "READY", ""
        self.model_id = "+".join(m["id"] for m in loaded)

    def _providers(self, ort, label: str) -> list:
        """CPU by default: these nets are tiny and CPU may beat CoreML. Use tools/pad_eval.py --benchmark
        to measure, then set PAD_PROVIDER=<label>. Nothing is assumed."""
        self.provider_label = "cpu"
        if label and label != "cpu":
            from face_engine import available_candidates
            for lab, provs in available_candidates("auto"):
                if lab == label:
                    self.provider_label = lab
                    return provs
        return ["CPUExecutionProvider"]

    # ---- inference
    def observe(self, frame_bgr: np.ndarray, bbox_xyxy: Sequence[float]) -> PADResult:
        if self._state != "READY":
            return PADResult(self._state, model_id=self.model_id, reason=self._reason)
        t0 = time.perf_counter()
        try:
            reals = []
            for m in self._models:
                x = preprocess(frame_bgr, bbox_xyxy, m["scale"], m["size"])
                probs = m["session"].run(None, {m["input_name"]: x})[0][0]
                reals.append(float(probs[m["real_index"]]))
            real = float(np.mean(reals))
        except Exception as exc:
            return PADResult(ERROR, model_id=self.model_id, reason=f"{type(exc).__name__}: {exc}",
                             latency_ms=(time.perf_counter() - t0) * 1000.0)
        spoof = 1.0 - real
        state = LIVE if real >= self.real_threshold else SPOOF if spoof >= self.spoof_threshold else UNCERTAIN
        return PADResult(state, real, spoof, self.model_id, (time.perf_counter() - t0) * 1000.0)

    def health(self) -> Dict:
        return {"state": self._state, "reason": self._reason, "model_id": self.model_id,
                "provider": self.provider_label,
                "models": [{"id": m["id"], "crop_scale": m["scale"]} for m in self._models]}


def build_pad(settings, model_dir: str = ANTISPOOFING_MODEL_DIR) -> PADProvider:
    """PAD provider for a Settings object: MiniFASNetPAD for liveness_mode == 'minifas', else NullPAD."""
    if getattr(settings, "liveness_mode", "off") != "minifas":
        return NullPAD("liveness_mode is not 'minifas'")
    return MiniFASNetPAD(model_dir, real_threshold=settings.pad_real_threshold,
                         spoof_threshold=settings.pad_spoof_threshold)


# ----------------------------------------------------------------------------- extension point
class ChallengeProvider(ABC):
    """Interface only (no implementation): randomized active challenges (turn head, blink) or depth/NIR
    sensors. Their output would be extra evidence for decide_pad, never proof by itself."""

    @abstractmethod
    def evidence(self, track_id: int, frame_bgr: np.ndarray, bbox_xyxy: Sequence[float]) -> Optional[float]:
        """Return a real-probability in [0, 1] or None when no evidence is available."""
