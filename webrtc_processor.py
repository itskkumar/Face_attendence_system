"""
webrtc_processor.py - per-viewer video processor for the browser-webcam option.

Each visitor who presses START gets their OWN GatePipeline (own tracker + identity state) while the
heavy models inside `engine` are shared. Kept in a separate module so it can be unit-tested with real
av.VideoFrame objects, independent of Streamlit's UI.
"""
import av
from streamlit_webrtc import VideoProcessorBase

from pipeline import GatePipeline


def make_processor_class(engine, store, settings):
    class FaceProcessor(VideoProcessorBase):
        def __init__(self):
            self.pipeline = GatePipeline(engine, store, settings, source_label="browser")
            self.last_info = None

        def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
            img = frame.to_ndarray(format="bgr24")
            out, self.last_info = self.pipeline.process(img)
            return av.VideoFrame.from_ndarray(out, format="bgr24")

    return FaceProcessor
