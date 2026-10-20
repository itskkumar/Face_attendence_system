"""
pages/1_Live_Feed.py - choose a video source in the browser and watch recognition run.

Sources
  1. Upload a CCTV / recorded video     -> every frame analysed (max accuracy), no frame dropping
  2. Video file on this computer (path) -> same, no upload size limit
  3. Server webcam                      -> the camera of the machine running Streamlit
  4. RTSP camera                        -> IP / CCTV gate camera
  5. Browser webcam (WebRTC)            -> the visitor's own camera (needs HTTPS when deployed)

Streamlit stops a running loop whenever you touch any widget, so the loops below are plain
`while` loops with a `finally` that always releases the camera.
"""
import os
import tempfile
import time

import cv2
import pandas as pd
import streamlit as st

from config import RTSP_URL, WEBCAM_INDEX
from pipeline import GatePipeline
from ui_common import get_engine, get_store, sidebar_settings
from video_sources import FpsLimiter, open_source

st.set_page_config(page_title="Live Feed", page_icon="📹", layout="wide")
st.title("📹 Live Camera & Video Feed")

engine = get_engine()
store = get_store()
settings = sidebar_settings()

SRC_UPLOAD = "Upload a video file (CCTV .mp4)"
SRC_PATH = "Video file on this computer (path)"
SRC_WEBCAM = "Server webcam (this machine)"
SRC_RTSP = "RTSP camera"
SRC_BROWSER = "Browser webcam (WebRTC)"
source = st.radio("Video source", [SRC_UPLOAD, SRC_PATH, SRC_WEBCAM, SRC_RTSP, SRC_BROWSER])

gallery_size = store.load_gallery().size
if gallery_size == 0:
    st.warning("No students enrolled yet - every face will show as Unknown. Use the Enrollment page first.")
else:
    st.caption(f"{gallery_size} enrolled student(s) loaded. New enrolments are picked up automatically.")
st.caption(f"Engine: **{engine.provider_label}** · detect every "
           f"{settings.file_detect_every_n if source in (SRC_UPLOAD, SRC_PATH) else settings.detect_every_n} frame(s)")

col_video, col_info = st.columns([3, 1])
frame_ph = col_video.empty()
progress_ph = col_video.empty()
status_ph = col_video.empty()
with col_info:
    st.markdown("**Live numbers**")
    m_unique, m_fps, m_faces = st.empty(), st.empty(), st.empty()
    st.markdown("**Recent log entries**")
    events_ph = st.empty()


def refresh_side(info) -> None:
    m_unique.metric("Unique people today", store.today_unique_count())
    if info:
        m_fps.metric("Processing FPS", f"{info['fps']:.1f}", f"{info['proc_ms']:.0f} ms / frame")
        m_faces.metric("Faces in view", info["faces"], f"{len(info['identified'])} recognised")
    rows = store.recent_entries(6)
    if rows:
        events_ph.dataframe(pd.DataFrame(rows)[["name", "roll_number", "timestamp"]], hide_index=True)
    else:
        events_ph.info("No entries yet")


def to_display(img):
    h, w = img.shape[:2]
    if w > settings.display_width:
        s = settings.display_width / w
        img = cv2.resize(img, (settings.display_width, int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def run_stream(reader, *, is_file: bool, label: str, save_annotated: bool = False) -> None:
    """Pump frames through the pipeline until the source ends or the user touches a widget."""
    if getattr(reader, "last_error", None):
        status_ph.error(reader.last_error)
        reader.release()
        return
    pipeline = GatePipeline(engine, store, settings, source_label=label, is_file=is_file)
    limiter = FpsLimiter(0 if is_file else settings.target_fps)
    writer, out_path = None, None
    frames, last_show, last_side, info = 0, 0.0, 0.0, None
    total = getattr(reader, "total_frames", 0) or 0
    try:
        while True:
            ok, frame = reader.read()
            if not ok:
                if is_file:
                    break
                status_ph.info("Waiting for the camera / stream ...")   # also lets Streamlit interrupt us
                if getattr(reader, "last_error", None):
                    status_ph.error(reader.last_error)
                continue
            out, info = pipeline.process(frame)
            frames += 1
            if save_annotated:
                if writer is None:
                    out_path = os.path.join(tempfile.gettempdir(), f"annotated_{int(time.time())}.mp4")
                    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                             getattr(reader, "native_fps", 0) or 25,
                                             (out.shape[1], out.shape[0]))
                writer.write(out)
            now = time.monotonic()
            if now - last_show >= 0.05:                                  # ~20 fps display, processing unaffected
                frame_ph.image(to_display(out), channels="BGR", output_format="JPEG")
                if total:
                    progress_ph.progress(min(frames / total, 1.0), text=f"frame {frames} / {total}")
                last_show = now
            if now - last_side >= 0.7:
                refresh_side(info)
                last_side = now
            limiter.wait()
        refresh_side(info)
        status_ph.success(f"Finished: {frames} frames processed, {pipeline.session_logged} attendance "
                          "entr(y/ies) logged in this run.")
    finally:
        reader.release()
        pipeline.close()
        if writer is not None:
            writer.release()
            st.session_state["annotated_path"] = out_path


def offer_annotated_download() -> None:
    path = st.session_state.get("annotated_path")
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            st.download_button("⬇ Download annotated video", f.read(), file_name="annotated_attendance.mp4",
                               mime="video/mp4")


refresh_side(None)

# ----------------------------------------------------------------------------- sources
if source == SRC_UPLOAD:
    up = st.file_uploader("CCTV clip or any recorded video", type=["mp4", "mov", "avi", "mkv", "m4v"])
    save = st.checkbox("Also save an annotated copy of the video", value=False)
    if st.button("▶ Process video", type="primary", disabled=up is None) and up is not None:
        suffix = os.path.splitext(up.name)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(up.getbuffer())
            path = tmp.name
        try:
            run_stream(open_source("file", path), is_file=True, label="upload", save_annotated=save)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    offer_annotated_download()

elif source == SRC_PATH:
    path = st.text_input("Full path to a video file", placeholder="/Users/you/Movies/gate_clip.mp4")
    save = st.checkbox("Also save an annotated copy of the video", value=False)
    if st.button("▶ Process video", type="primary"):
        if not path or not os.path.isfile(path):
            status_ph.error("File not found. Paste the full path (drag the file into Terminal to get it).")
        else:
            run_stream(open_source("file", path), is_file=True, label="file", save_annotated=save)
    offer_annotated_download()

elif source == SRC_WEBCAM:
    idx = st.number_input("Webcam index", 0, 5, WEBCAM_INDEX)
    st.caption("This is the camera of the computer running Streamlit. macOS asks for camera permission "
               "the first time - allow it for your terminal app, then restart the terminal.")
    if st.toggle("▶ Start webcam", key="run_webcam"):
        run_stream(open_source("webcam", int(idx)), is_file=False, label="webcam")

elif source == SRC_RTSP:
    url = st.text_input("RTSP URL", value=RTSP_URL)
    st.caption("Test the URL in VLC first (Media > Open Network Stream). Sub-streams "
               "(e.g. .../Channels/102) are lighter on the CPU than main streams.")
    if st.toggle("▶ Connect", key="run_rtsp"):
        run_stream(open_source("rtsp", url), is_file=False, label="rtsp")

else:  # ----------------------------------------------------------------- browser webcam
    try:
        from streamlit_autorefresh import st_autorefresh
        from streamlit_webrtc import WebRtcMode, webrtc_streamer
        from webrtc_processor import make_processor_class
    except Exception as exc:
        st.error(f"streamlit-webrtc is not available: {exc}")
        st.stop()
    st.info("Uses the camera of whoever opens this page, through the browser (WebRTC). It works on "
            "`localhost` and on HTTPS sites; a public deployment may also need a TURN server. "
            "Change a sidebar setting, then press STOP / START to apply it.")
    FaceProcessor = make_processor_class(engine, store, settings)

    ctx = webrtc_streamer(
        key="face-attendance-webrtc", mode=WebRtcMode.SENDRECV, video_processor_factory=FaceProcessor,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        media_stream_constraints={"video": {"width": {"ideal": 960}}, "audio": False},
        async_processing=True)
    if ctx.state.playing:
        st_autorefresh(interval=2000, key="webrtc_refresh")      # keep the side numbers fresh
        refresh_side(None)
