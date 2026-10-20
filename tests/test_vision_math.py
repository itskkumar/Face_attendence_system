import cv2, numpy as np, pytest
from vision_math import (ARCFACE_REF, align_face, fft_moire_score, l2_normalize,
                         laplacian_variance, pose_score, umeyama_similarity)


def _transform(points, scale, theta, t):
    R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    return scale * points @ R.T + t


def test_umeyama_recovers_known_similarity_transform():
    # landmarks in an image = reference landmarks moved by a known similarity transform
    scale, theta, t = 1.7, np.deg2rad(18), np.array([140.0, 90.0])
    detected = _transform(ARCFACE_REF, scale, theta, t)
    c, R, tt, M = umeyama_similarity(detected, ARCFACE_REF)      # map detected -> canonical
    assert np.allclose(c, 1 / scale, atol=1e-9)
    mapped = detected @ (c * R).T + tt
    assert np.allclose(mapped, ARCFACE_REF, atol=1e-8)
    assert np.isclose(np.linalg.det(R), 1.0)                      # a rotation, never a reflection


def test_umeyama_is_least_squares_under_noise():
    rng = np.random.default_rng(0)
    detected = _transform(ARCFACE_REF, 2.0, 0.2, np.array([50., 60.])) + rng.normal(0, 0.5, (5, 2))
    c, R, t, M = umeyama_similarity(detected, ARCFACE_REF)
    err = np.linalg.norm(detected @ (c * R).T + t - ARCFACE_REF, axis=1).mean()
    assert err < 1.5
    # beats a perturbed solution
    M2 = np.hstack([c * R * 1.02, (t + 1.0)[:, None]])
    err2 = np.linalg.norm(detected @ M2[:, :2].T + M2[:, 2] - ARCFACE_REF, axis=1).mean()
    assert err < err2


def test_umeyama_matches_insightface_reference():
    face_align = pytest.importorskip("insightface.utils.face_align")
    rng = np.random.default_rng(3)
    kps = _transform(ARCFACE_REF, 2.3, 0.15, np.array([300., 200.])) + rng.normal(0, 1.0, (5, 2))
    M_ref = face_align.estimate_norm(kps.astype(np.float32), 112)
    M_mine = umeyama_similarity(kps, ARCFACE_REF)[3]
    assert np.allclose(M_ref, M_mine, atol=1e-3)


def test_degenerate_landmarks_rejected():
    with pytest.raises(ValueError):
        umeyama_similarity(np.ones((5, 2)), ARCFACE_REF)


def test_align_face_output_shape():
    frame = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    kps = _transform(ARCFACE_REF, 1.5, 0.1, np.array([250., 150.]))
    aligned, M = align_face(frame, kps)
    assert aligned.shape == (112, 112, 3) and M.shape == (2, 3)


def test_blur_score_orders_sharp_above_blurred():
    rng = np.random.default_rng(1)
    sharp = rng.integers(0, 255, (112, 112, 3), dtype=np.uint8)
    blurred = cv2.GaussianBlur(sharp, (0, 0), 4)
    assert laplacian_variance(sharp) > 10 * laplacian_variance(blurred)


def test_pose_score_frontal_vs_profile():
    frontal = ARCFACE_REF.copy()
    profile = ARCFACE_REF.copy(); profile[2, 0] = profile[1, 0] - 2   # nose almost on right eye
    assert pose_score(frontal) > 0.9
    assert pose_score(profile) < 0.4
    assert pose_score(np.array([[10, 0], [10, 0], [10, 0], [0, 0], [0, 0]], float)) == 0.0


def test_l2_normalize():
    v = l2_normalize(np.array([3.0, 4.0]))
    assert np.isclose(np.linalg.norm(v), 1.0)
    assert np.allclose(l2_normalize(np.zeros(4)), 0.0)


def test_fft_score_in_range():
    img = np.random.default_rng(2).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    assert 0.0 <= fft_moire_score(img) <= 1.0
