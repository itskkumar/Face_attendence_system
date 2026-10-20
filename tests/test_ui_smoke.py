"""Headless smoke tests of the Streamlit pages (streamlit.testing.v1.AppTest) with the REAL models."""
import os

import cv2
import numpy as np
import pytest

pytest.importorskip("streamlit")
pytest.importorskip("insightface")
from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT = 180


def page(path):
    return AppTest.from_file(os.path.join(ROOT, path), default_timeout=TIMEOUT)


def test_dashboard_renders_and_counts_update():
    from database import Store
    at = page("dashboard.py").run()
    assert not at.exception
    assert any("Unique people entered today" in m.value for m in at.markdown)
    store = Store()
    store.add_student("UI1", "Ui Tester", [np.random.default_rng(1).normal(size=512)])
    store.log_attendance("UI1", "Ui Tester", 1, 0.8, "ENTRY", "test", 300)
    at = page("dashboard.py").run()
    assert not at.exception
    assert any(">1</div>" in m.value for m in at.markdown)            # big number now shows 1
    assert len(at.dataframe) >= 1


def test_enrollment_page_renders_and_save_disabled_without_samples():
    at = page("pages/2_Enrollment.py").run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Enrol a student", "Enrolled students"]
    save = [b for b in at.button if "Save student" in b.label][0]
    assert save.disabled


@pytest.mark.parametrize("choice", ["Upload a video file (CCTV .mp4)", "Video file on this computer (path)",
                                    "Server webcam (this machine)", "RTSP camera", "Browser webcam (WebRTC)"])
def test_live_page_every_source_renders_without_error(choice, monkeypatch):
    # AppTest swaps Streamlit's Runtime for a mock, which the streamlit-webrtc *widget* cannot work
    # with; stub only that widget. The processor it would run is tested in test_webrtc_processor.py.
    import types
    import streamlit_webrtc
    monkeypatch.setattr(streamlit_webrtc, "webrtc_streamer",
                        lambda **kw: types.SimpleNamespace(state=types.SimpleNamespace(playing=False)))
    at = page("pages/1_Live_Feed.py").run()
    assert not at.exception
    at.radio[0].set_value(choice).run()
    assert not at.exception, [e.value for e in at.exception]


def test_live_page_processes_a_video_file_end_to_end(tmp_path):
    from insightface.data import get_image
    photo = get_image("t1")
    clip = str(tmp_path / "clip.mp4")
    h, w = photo.shape[:2]
    vw = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 25, (w, h))
    for f in range(8):
        vw.write(np.roll(photo, f * 2, axis=1))
    vw.release()

    at = page("pages/1_Live_Feed.py").run()
    at.radio[0].set_value("Video file on this computer (path)").run()
    at.text_input[0].set_value(clip).run()
    [b for b in at.button if "Process video" in b.label][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    import re
    done = [re.search(r"Finished: (\d+) frames processed", s.value) for s in at.success]
    done = [int(m.group(1)) for m in done if m]
    assert done and done[0] >= 7        # a tiny mp4v clip may lose its first (non-key) frame in the decoder
