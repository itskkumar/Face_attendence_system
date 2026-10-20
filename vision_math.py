"""
vision_math.py - the numerical building blocks of the pipeline.

Everything here is plain NumPy/OpenCV and unit-tested (tests/test_vision_math.py):

  * umeyama_similarity : least-squares similarity transform via SVD
  * align_face         : warp a face to the canonical 112x112 ArcFace layout
  * laplacian_variance : sharpness / motion-blur score
  * pose_score         : cheap frontal-ness estimate from the 5 landmarks
  * fft_moire_score    : EXPERIMENTAL screen-replay heuristic (off by default)
"""
from __future__ import annotations

import cv2
import numpy as np

# Canonical 5-point layout of a 112x112 ArcFace crop:
# left eye, right eye, nose tip, left mouth corner, right mouth corner.
ARCFACE_REF = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)


def l2_normalize(v: np.ndarray, axis: int = -1) -> np.ndarray:
    """Project onto the unit hypersphere. Zero vectors are returned unchanged."""
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def umeyama_similarity(src: np.ndarray, dst: np.ndarray):
    """
    Solve  min_{c,R,t} sum_i || dst_i - (c R src_i + t) ||^2   (Umeyama, 1991).

    With centred point sets P (src) and Q (dst) and covariance
        Sigma = (1/n) Q^T P = U D V^T      (SVD)
    the optimum is  R = U S V^T,  c = tr(D S) / var(P),  t = mu_q - c R mu_p,
    where S = diag(1, det(U V^T)) rules out reflections.

    Returns (scale, R (2x2), t (2,), M (2x3 affine matrix)).
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2:
        raise ValueError("src and dst must both be (N, 2)")
    n = src.shape[0]
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    sc, dc = src - mu_s, dst - mu_d
    var_s = float((sc ** 2).sum() / n)
    if var_s < 1e-12:
        raise ValueError("degenerate source landmarks (zero variance)")
    cov = dc.T @ sc / n
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[1, 1] = -1.0
    R = U @ S @ Vt
    scale = float((D * np.diag(S)).sum() / var_s)
    t = mu_d - scale * (R @ mu_s)
    M = np.hstack([scale * R, t[:, None]])
    return scale, R, t, M


def align_face(frame_bgr: np.ndarray, kps: np.ndarray, size: int = 112):
    """Warp the face to the canonical crop. Returns (aligned_bgr, M 2x3)."""
    ref = ARCFACE_REF * (size / 112.0)
    _, _, _, M = umeyama_similarity(kps, ref)
    aligned = cv2.warpAffine(
        frame_bgr, M.astype(np.float32), (size, size),
        flags=cv2.INTER_LINEAR, borderValue=0,
    )
    return aligned, M


def laplacian_variance(img_bgr: np.ndarray) -> float:
    """Var(nabla^2 I): high for sharp faces, low for blurred / motion-smeared ones."""
    gray = img_bgr if img_bgr.ndim == 2 else cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def pose_score(kps: np.ndarray) -> float:
    """
    Frontal-ness in [0, 1] from horizontal nose placement between the eyes:
        1 - | (x_nose - x_le) - (x_re - x_nose) | / (x_re - x_le)
    1.0 means the nose is exactly centred (frontal); it falls as the head yaws.
    """
    le, re, nose = float(kps[0][0]), float(kps[1][0]), float(kps[2][0])
    eye_dist = re - le
    if eye_dist <= 1.0:
        return 0.0
    asym = abs((nose - le) - (re - nose)) / eye_dist
    return float(np.clip(1.0 - asym, 0.0, 1.0))


def cosine_similarity_matrix(gallery: np.ndarray, query: np.ndarray) -> np.ndarray:
    """For L2-normalised vectors cosine similarity is a plain inner product."""
    return gallery @ query


def fft_moire_score(aligned_bgr: np.ndarray) -> float:
    """
    EXPERIMENTAL / UNVALIDATED liveness heuristic - do not rely on it for security.

    Photos re-captured from a screen can show periodic moire peaks in the 2D
    spectrum. This measures how "spiky" the high-frequency band is relative to
    its median; spiky -> low score. Returns a score in [0, 1], higher = more
    likely a real face. Thresholds were NOT tuned on real spoof data. A trained
    anti-spoofing network (e.g. MiniFASNet) is the proper replacement.
    """
    gray = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    spec = np.fft.fftshift(np.fft.fft2((gray - gray.mean()) * win))
    mag = np.log1p(np.abs(spec))
    yy, xx = np.ogrid[:h, :w]
    radius = np.hypot(yy - h / 2.0, xx - w / 2.0)
    band = mag[radius >= 0.30 * min(h, w)]
    if band.size == 0:
        return 0.0
    peakiness = float(band.max() / (np.median(band) + 1e-6))
    return float(np.clip(1.0 - (peakiness - 2.5) / 4.0, 0.0, 1.0))
