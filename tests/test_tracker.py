import numpy as np
from tracker import ByteTrackLite, Detection, KalmanFilterXYAH, iou_matrix, xyah_to_xyxy, xyxy_to_xyah


def box(cx, cy, w=80, h=100):
    return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], float)


def test_box_conversion_roundtrip():
    b = box(300, 200, 90, 120)
    assert np.allclose(xyah_to_xyxy(xyxy_to_xyah(b)), b)


def test_iou():
    a = np.array([[0, 0, 10, 10.]]); b = np.array([[5, 0, 15, 10.], [20, 20, 30, 30.]])
    m = iou_matrix(a, b)
    assert np.isclose(m[0, 0], 50 / 150) and m[0, 1] == 0


def test_kalman_tracks_constant_velocity():
    kf = KalmanFilterXYAH()
    mean, cov = kf.initiate(xyxy_to_xyah(box(100, 100)))
    for k in range(1, 30):
        mean, cov = kf.predict(mean, cov)
        mean, cov = kf.update(mean, cov, xyxy_to_xyah(box(100 + 5 * k, 100 + 2 * k)))
    assert abs(mean[4] - 5) < 0.6 and abs(mean[5] - 2) < 0.6          # learned the velocity
    pm, pc = kf.predict(mean, cov)
    assert abs(pm[0] - (100 + 5 * 30)) < 8                            # predicts the next position


def test_gating_distance_separates_near_and_far():
    kf = KalmanFilterXYAH()
    mean, cov = kf.initiate(xyxy_to_xyah(box(100, 100)))
    mean, cov = kf.predict(mean, cov)
    near = xyxy_to_xyah(box(103, 101)); far = xyxy_to_xyah(box(400, 300))
    d = kf.gating_distance(mean, cov, np.array([near, far]))
    assert d[0] < 13.28 < d[1]


def _run(trajs, frames=80, drop=0.0, seed=0, low_score_every=None):
    rng = np.random.default_rng(seed)
    tr = ByteTrackLite()
    seen = {k: set() for k in range(len(trajs))}
    for f in range(frames):
        tr.predict()
        dets, truth = [], []
        for k, fn in enumerate(trajs):
            cx, cy = fn(f)
            if rng.random() < drop:
                continue
            score = 0.9
            if low_score_every and f % low_score_every == 0:
                score = 0.3                                          # blurred / half-hidden frame
            dets.append(Detection(box(cx + rng.normal(0, 1), cy + rng.normal(0, 1)), None, score))
            truth.append(k)
        tr.update(dets)
        for t in tr.tracks:
            if t.confirmed and t.time_since_update == 0:
                c = np.array(t.center)
                k = int(np.argmin([np.hypot(*(c - np.array(fn(f)))) for fn in trajs]))
                seen[k].add(t.id)
    return seen


def test_three_people_walking_together_keep_distinct_stable_ids():
    trajs = [lambda f: (100 + 6 * f, 200), lambda f: (140 + 6 * f, 400), lambda f: (60 + 6 * f, 300)]
    seen = _run(trajs)
    assert all(len(ids) == 1 for ids in seen.values())                 # one id each, no switches
    assert len({next(iter(i)) for i in seen.values()}) == 3


def test_ids_survive_missed_detections():
    trajs = [lambda f: (100 + 5 * f, 200), lambda f: (500 - 5 * f, 260)]
    seen = _run(trajs, drop=0.25, seed=4)
    assert all(len(ids) == 1 for ids in seen.values())


def test_low_confidence_second_stage_prevents_fragmentation():
    trajs = [lambda f: (100 + 5 * f, 200)]
    seen = _run(trajs, low_score_every=3)
    assert len(seen[0]) == 1


def test_people_crossing_paths_keep_ids():
    # Realistic crossing: people at different heights in the frame. (Two IDENTICAL boxes at the
    # same height that overlap exactly are inherently ambiguous for any motion-only tracker -
    # the pipeline guards that case separately by re-verifying identity with ArcFace.)
    trajs = [lambda f: (100 + 8 * f, 200 + 2 * f), lambda f: (740 - 8 * f, 245 + 2 * f)]
    seen = _run(trajs, frames=80)
    assert all(len(ids) == 1 for ids in seen.values())


def test_lost_tracks_are_pruned_and_ghosts_never_confirmed():
    tr = ByteTrackLite(max_age=10)
    tr.predict(); tr.update([Detection(box(100, 100), None, 0.9)])
    assert not tr.tracks[0].confirmed
    for _ in range(6):
        tr.predict(); tr.update([])
    assert tr.tracks == []                                             # tentative ghost removed
    for _ in range(3):
        tr.predict(); tr.update([Detection(box(100, 100), None, 0.9)])
    assert tr.tracks[0].confirmed
    for _ in range(12):
        tr.predict(); tr.update([])
    assert tr.tracks == []
