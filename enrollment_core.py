"""
enrollment_core.py - turn one photo/frame into a quality-checked face template.

Shared by enrollment.py (CLI) and pages/2_Enrollment.py (web UI). Enrolment
gates are slightly relaxed on pose (people are asked to turn a little on
purpose) but strict on blur, size and single-face.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from config import Settings
from vision_math import align_face, laplacian_variance, pose_score


@dataclass
class EnrollSample:
    embedding: np.ndarray
    quality: float
    aligned: np.ndarray        # 112x112 BGR, for thumbnails
    blur: float
    pose: float


def analyze_face_for_enrollment(engine, frame_bgr: np.ndarray, settings: Settings,
                                min_pose: float = 0.30):
    """Returns (EnrollSample | None, reason). reason is '' on success."""
    dets = [d for d in engine.detect(frame_bgr) if d.kps is not None and d.score >= 0.5]
    if not dets:
        return None, "No face found"
    dets.sort(key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]), reverse=True)
    best = dets[0]
    area = lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1])
    if len(dets) > 1 and area(dets[1]) > 0.35 * area(best):
        return None, "More than one face - only the person being enrolled should be visible"
    if best.score < 0.70:
        return None, "Face not clear enough (low detector confidence)"
    width = float(best.bbox[2] - best.bbox[0])
    if width < 80:
        return None, f"Face too small ({width:.0f}px) - move closer"
    ps = pose_score(best.kps)
    if ps < min_pose:
        return None, "Head turned too far"
    aligned, _ = align_face(frame_bgr, best.kps)
    blur = laplacian_variance(aligned)
    if blur < settings.enroll_min_blur_var:
        return None, f"Image is blurry (sharpness {blur:.0f} < {settings.enroll_min_blur_var:.0f})"
    emb = engine.embed_aligned(aligned)
    quality = float(np.clip(blur / 150.0, 0.1, 1.0) * max(ps, 0.3))
    return EnrollSample(emb, quality, aligned, blur, ps), ""
