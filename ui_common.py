"""ui_common.py - helpers shared by the Streamlit pages."""
import dataclasses

import streamlit as st

from config import DEFAULT_SETTINGS, Settings
from database import Store


@st.cache_resource(show_spinner="Loading face models (the first start downloads ~280 MB)...")
def get_engine():
    from face_engine import FaceEngine
    return FaceEngine(DEFAULT_SETTINGS)


@st.cache_resource
def get_store() -> Store:
    return Store()


def sidebar_settings() -> Settings:
    """Live-tunable settings. Moving a slider restarts the running stream with the new values."""
    d = DEFAULT_SETTINGS
    with st.sidebar:
        st.header("Recognition tuning")
        sim = st.slider("Similarity threshold", 0.25, 0.80, d.similarity_threshold, 0.01,
                        help="Cosine similarity needed to accept a match. Higher = stricter (fewer false "
                             "accepts, more 'Unknown'). Different people typically score below 0.25.")
        blur = st.slider("Min. sharpness (live)", 0.0, 200.0, d.min_blur_var, 1.0,
                         help="Faces blurrier than this are skipped (the amber label says 'blurry').")
        pose = st.slider("Min. frontal-ness", 0.0, 1.0, d.min_pose_score, 0.05,
                         help="1.0 = looking straight at the camera. Turned faces are skipped.")
        every = st.slider("Detect every N frames (live)", 1, 6, d.detect_every_n,
                          help="Higher = cooler and faster, boxes are still drawn every frame by the tracker.")
        cooldown = st.slider("Cooldown (minutes)", 1, 30, d.cooldown_seconds // 60,
                             help="A person is logged at most once per this window.")
        st.subheader("Virtual gate line")
        gate = st.checkbox("Enable ENTRY / EXIT line", value=d.gate_line_enabled)
        orient = st.radio("Line orientation", ["horizontal", "vertical"], horizontal=True,
                          index=0 if d.gate_line_orientation == "horizontal" else 1)
        ratio = st.slider("Line position", 0.1, 0.9, d.gate_line_ratio, 0.01)
        entry = st.selectbox("Moving this way = ENTRY", ["down", "up", "right", "left"],
                             index=["down", "up", "right", "left"].index(d.gate_entry_direction))
        need = st.checkbox("Log only after the line is crossed", value=d.require_gate_crossing)
        st.subheader("Experimental")
        live = st.checkbox("FFT liveness check (unvalidated heuristic)", value=False,
                           help="Not reliable anti-spoofing. A trained model (e.g. MiniFASNet) is needed "
                                "for real protection.")
    return dataclasses.replace(
        d, similarity_threshold=sim, min_blur_var=blur, min_pose_score=pose, detect_every_n=every,
        cooldown_seconds=cooldown * 60, gate_line_enabled=gate, gate_line_orientation=orient,
        gate_line_ratio=ratio, gate_entry_direction=entry, require_gate_crossing=need,
        liveness_mode="fft_experimental" if live else "off")
