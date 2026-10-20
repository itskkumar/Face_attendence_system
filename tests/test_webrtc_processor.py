"""The browser-webcam path: real av.VideoFrame in -> annotated av.VideoFrame out, real models."""
import dataclasses

import av
import numpy as np
import pytest

pytest.importorskip("streamlit_webrtc")
pytest.importorskip("insightface")
from config import DEFAULT_SETTINGS
from database import Store
from enrollment_core import analyze_face_for_enrollment

try:
    from face_engine import CPU_SPEC, FaceEngine
    ENGINE = FaceEngine(DEFAULT_SETTINGS, candidates=[CPU_SPEC])
except Exception as exc:
    pytest.skip(f"real models unavailable: {exc}", allow_module_level=True)

from webrtc_processor import make_processor_class


def test_processor_recognises_logs_and_returns_annotated_frames(tmp_path):
    from insightface.data import get_image
    photo = get_image("t1")
    from vision_math import pose_score
    best = max(ENGINE.detect(photo), key=lambda d: pose_score(d.kps))
    b = best.bbox
    cx, cy, side = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 1.9 * max(b[2] - b[0], b[3] - b[1])
    crop = photo[int(max(0, cy - side / 2)):int(cy + side / 2), int(max(0, cx - side / 2)):int(cx + side / 2)]
    sample, reason = analyze_face_for_enrollment(ENGINE, crop, DEFAULT_SETTINGS)
    assert sample is not None, reason

    store = Store(str(tmp_path / "w.db"))
    store.add_student("W1", "Web Viewer", [sample.embedding], [sample.quality])
    settings = dataclasses.replace(DEFAULT_SETTINGS, detect_every_n=1, rec_interval_frames=1)
    proc = make_processor_class(ENGINE, store, settings)()          # exactly how streamlit-webrtc builds it

    out = None
    for _ in range(10):
        out = proc.recv(av.VideoFrame.from_ndarray(photo, format="bgr24"))   # same type the browser path delivers
    assert isinstance(out, av.VideoFrame)
    arr = out.to_ndarray(format="bgr24")
    assert arr.shape == photo.shape and not np.array_equal(arr, photo)       # boxes/HUD drawn
    assert "Web Viewer" in proc.last_info["identified"]
    logs = store.all_logs()
    assert len(logs) == 1 and logs[0]["roll_number"] == "W1" and logs[0]["source"] == "browser"


def test_two_viewers_have_independent_pipelines(tmp_path):
    store = Store(str(tmp_path / "w2.db"))
    cls = make_processor_class(ENGINE, store, DEFAULT_SETTINGS)
    a, b = cls(), cls()
    assert a.pipeline is not b.pipeline and a.pipeline.tracker is not b.pipeline.tracker
