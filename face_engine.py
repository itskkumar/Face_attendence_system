"""
face_engine.py - InsightFace buffalo_l wrapper tuned for Apple Silicon.

Models (from InsightFace's `buffalo_l` pack, run through ONNXRuntime):
  * detection   : det_10g.onnx  - SCRFD-10G with 5-point landmarks (InsightFace's Python
                  class that executes it is named `RetinaFace`, but the weights are SCRFD)
  * recognition : w600k_r50.onnx - ArcFace ResNet-50 trained on WebFace600K, 512-d output

Only these two modules are used (no age/gender/3D landmarks), which saves memory
and start-up time versus FaceAnalysis.get().

Hardware acceleration: ONNXRuntime's CoreMLExecutionProvider (Apple Neural
Engine / GPU). Whether CoreML is actually FASTER than the CPU provider depends
on the model and ONNXRuntime version - small models can lose to CPU because of
graph-partitioning overhead - so `benchmark.py` measures both and records the
winner, and this module falls back automatically if CoreML fails to load.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from config import PROVIDER_CACHE_PATH, Settings
from tracker import Detection
from vision_math import align_face, l2_normalize

ProviderSpec = Tuple[str, list]   # (label, providers argument for onnxruntime)

CPU_SPEC: ProviderSpec = ("cpu", ["CPUExecutionProvider"])
COREML_FAST: ProviderSpec = (
    "coreml-mlprogram-all",
    [("CoreMLExecutionProvider", {"ModelFormat": "MLProgram", "MLComputeUnits": "ALL"}),
     "CPUExecutionProvider"],
)
COREML_DEFAULT: ProviderSpec = (
    "coreml-default", ["CoreMLExecutionProvider", "CPUExecutionProvider"],
)


def available_candidates(mode: str) -> List[ProviderSpec]:
    """Provider configurations to try, in order, for the requested mode."""
    import onnxruntime as ort

    has_coreml = "CoreMLExecutionProvider" in ort.get_available_providers()
    if mode == "cpu" or not has_coreml:
        return [CPU_SPEC]
    if mode == "coreml":
        return [COREML_FAST, COREML_DEFAULT, CPU_SPEC]
    # auto: honour a previous benchmark if there is one
    if os.path.exists(PROVIDER_CACHE_PATH):
        try:
            with open(PROVIDER_CACHE_PATH) as f:
                choice = json.load(f).get("choice")
            by_label = {s[0]: s for s in (COREML_FAST, COREML_DEFAULT, CPU_SPEC)}
            if choice in by_label:
                rest = [s for s in (COREML_FAST, COREML_DEFAULT, CPU_SPEC) if s[0] != choice]
                return [by_label[choice]] + rest
        except (OSError, ValueError):
            pass
    return [COREML_FAST, COREML_DEFAULT, CPU_SPEC]


class FaceEngine:
    def __init__(self, settings: Settings, candidates: Optional[Sequence[ProviderSpec]] = None):
        self.s = settings
        self.provider_label = "unknown"
        self.det_model = None
        self.rec_model = None
        errors = []
        for label, providers in (candidates or available_candidates(settings.provider_mode)):
            try:
                self._load(providers)
                self._warmup()
                self.provider_label = label
                break
            except Exception as exc:                     # CoreML can fail on some ORT builds
                errors.append(f"{label}: {exc}")
                self.det_model = self.rec_model = None
        else:
            raise RuntimeError("Could not initialise any ONNXRuntime provider:\n  " + "\n  ".join(errors))
        if errors:
            print("[face_engine] skipped providers ->", " | ".join(errors))
        print(f"[face_engine] ready with provider config '{self.provider_label}'")

    def _load(self, providers: list) -> None:
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"],
                           providers=providers)
        # NOTE: ctx_id must stay >= 0 here; ctx_id=-1 would force the CPU provider.
        app.prepare(ctx_id=0, det_size=(self.s.det_size, self.s.det_size),
                    det_thresh=self.s.det_low_thresh)
        self.det_model = app.models["detection"]
        self.rec_model = app.models["recognition"]

    def _warmup(self) -> None:
        """First inference compiles CoreML graphs; do it now so the video never stalls."""
        self.det_model.detect(np.zeros((480, 640, 3), np.uint8), max_num=0, metric="default")
        self.rec_model.get_feat(np.zeros((112, 112, 3), np.uint8))

    # ------------------------------------------------------------------ API
    def detect(self, frame_bgr: np.ndarray) -> List[Detection]:
        """All faces in the frame, coordinates in the ORIGINAL frame's pixels."""
        h, w = frame_bgr.shape[:2]
        scale = 1.0
        img = frame_bgr
        if self.s.process_width and w > self.s.process_width:
            scale = self.s.process_width / float(w)
            img = cv2.resize(frame_bgr, (int(round(w * scale)), int(round(h * scale))),
                             interpolation=cv2.INTER_AREA)
        bboxes, kpss = self.det_model.detect(img, max_num=0, metric="default")
        dets: List[Detection] = []
        if bboxes is None:
            return dets
        for i in range(bboxes.shape[0]):
            kps = None if kpss is None else (kpss[i] / scale).astype(np.float64)
            dets.append(Detection(bbox=(bboxes[i, :4] / scale).astype(np.float64),
                                  kps=kps, score=float(bboxes[i, 4])))
        return dets

    def embed_aligned(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """512-d L2-normalised ArcFace embedding of a 112x112 aligned crop."""
        feat = self.rec_model.get_feat(aligned_bgr).flatten()
        return l2_normalize(feat)

    def embed(self, frame_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        aligned, _ = align_face(frame_bgr, kps)
        return self.embed_aligned(aligned)
