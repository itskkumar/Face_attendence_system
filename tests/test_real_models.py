"""
REAL-model integration test (InsightFace buffalo_l, CPU or CoreML):
  * enrol 3 of the 6 people in InsightFace's sample group photo from tight crops (with augmented copies)
  * build a short video of that photo drifting/zooming with brightness change + sensor noise + MP4 compression
  * run the real pipeline over the video file
Expected: the 3 enrolled people are logged exactly once, the other faces are never logged.
Skipped automatically if InsightFace or its models are unavailable.
"""
import dataclasses
import os

import cv2
import numpy as np
import pytest

insightface = pytest.importorskip("insightface")
from config import DEFAULT_SETTINGS
from database import Store
from enrollment_core import analyze_face_for_enrollment
from pipeline import GatePipeline
from video_sources import FileReader

try:
    from face_engine import CPU_SPEC, FaceEngine
    ENGINE = FaceEngine(DEFAULT_SETTINGS, candidates=[CPU_SPEC])
except Exception as exc:                                   # models could not be downloaded/loaded
    pytest.skip(f"real models unavailable: {exc}", allow_module_level=True)


def _augment(img, rng):
    out = []
    for gain, angle, blur in [(1.0, 0, 0), (1.15, 4, 0), (0.85, -4, 0)]:
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        a = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        a = np.clip(a.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        if blur:
            a = cv2.GaussianBlur(a, (0, 0), blur)
        out.append(a)
    return out


@pytest.fixture(scope="module")
def scene(tmp_path_factory):
    from insightface.data import get_image
    photo = get_image("t1")
    from vision_math import pose_score
    dets = sorted(ENGINE.detect(photo), key=lambda d: -pose_score(d.kps))   # most frontal first
    assert len(dets) == 6
    return photo, dets, tmp_path_factory.mktemp("real")


def test_real_models_end_to_end(scene):
    photo, dets, tmp = scene
    store = Store(str(tmp / "real.db"))
    rng = np.random.default_rng(0)
    enrolled = {0: ("R0", "Person Zero"), 1: ("R2", "Person Two"), 2: ("R3", "Person Three")}   # 3 most frontal faces

    # ---- enrolment from tight crops, 3 augmented samples each
    for idx, (roll, name) in enrolled.items():
        b = dets[idx].bbox
        cx, cy, side = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 1.9 * max(b[2] - b[0], b[3] - b[1])
        x1, y1 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
        crop = photo[y1:int(cy + side / 2), x1:int(cx + side / 2)]
        samples = []
        for aug in _augment(crop, rng):
            s, reason = analyze_face_for_enrollment(ENGINE, aug, DEFAULT_SETTINGS)
            assert s is not None, f"{name}: {reason}"
            samples.append(s)
        assert store.find_duplicate_identity([s.embedding for s in samples], roll) is None
        store.add_student(roll, name, [s.embedding for s in samples], [s.quality for s in samples])
    assert store.load_gallery().size == 3

    # ---- synthetic CCTV clip: drift + zoom + brightness flicker + noise, MP4-compressed
    path = str(tmp / "clip.mp4")
    h, w = photo.shape[:2]
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    for f in range(48):
        z = 1.0 + 0.0015 * f
        M = np.array([[z, 0, -0.5 * (z - 1) * w + 0.4 * f], [0, z, -0.5 * (z - 1) * h + 0.2 * f]], np.float32)
        fr = cv2.warpAffine(photo, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        fr = np.clip(fr.astype(np.float32) * (1 + 0.06 * np.sin(f / 5)) + rng.normal(0, 3, fr.shape), 0, 255)
        vw.write(fr.astype(np.uint8))
    vw.release()

    # ---- run the real pipeline over the file
    settings = dataclasses.replace(DEFAULT_SETTINGS, file_detect_every_n=2)
    pipe = GatePipeline(ENGINE, store, settings, source_label="clip", is_file=True)
    reader = FileReader(path)
    assert reader.opened and reader.total_frames >= 40
    last = None
    while True:
        ok, frame = reader.read()
        if not ok:
            break
        out, last = pipe.process(frame)
    reader.release()

    logs = store.all_logs()
    rolls = sorted(r["roll_number"] for r in logs)
    print("\nlogged:", [(r["roll_number"], round(r["similarity"], 2)) for r in logs])
    print("final frame:", {k: last[k] for k in ("faces", "identified", "unknown")})
    states = sorted((t.ident.status, t.ident.hint) for t in pipe.tracker.tracks if t.confirmed and t.ident)
    print("track states:", states)
    assert rolls == ["R0", "R2", "R3"]                       # enrolled people logged exactly once each
    assert all(r["similarity"] >= DEFAULT_SETTINGS.similarity_threshold for r in logs)
    assert sorted(last["identified"]) == ["Person Three", "Person Two", "Person Zero"]
    # the 3 strangers: one frontal enough to be judged (Unknown), two turned away (not judged at all)
    status = sorted(s for s, _ in states)
    assert status == ["identified"] * 3 + ["pending"] * 2 + ["unknown"]
    assert [h for s, h in states if s == "pending"] == ["face the camera"] * 2
