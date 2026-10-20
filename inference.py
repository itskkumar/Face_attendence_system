"""
inference.py - live gate engine (Module B), runs in a terminal.

  python inference.py --source webcam
  python inference.py --source rtsp --url rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101
  python inference.py --source file --path gate_clip.mp4 --no-display

Detects every face in every processed frame (groups are fine), tracks each
person, recognises them from quality keyframes and logs attendance once per
cooldown window. Press q in the video window (or Ctrl+C) to stop.
"""
import argparse
import dataclasses
import sys
import time

import cv2

import config
from config import DEFAULT_SETTINGS, DEFAULT_SOURCE, RTSP_PLACEHOLDER_MARKER, RTSP_URL, WEBCAM_INDEX
from database import Store
from face_engine import FaceEngine
from pipeline import GatePipeline
from video_sources import FpsLimiter, open_source

WINDOW = "Gate Camera - Live Attendance (q to quit)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Live face-attendance engine")
    ap.add_argument("--source", choices=["rtsp", "webcam", "file"], default=DEFAULT_SOURCE)
    ap.add_argument("--url", default=RTSP_URL)
    ap.add_argument("--index", type=int, default=WEBCAM_INDEX)
    ap.add_argument("--path", help="video file for --source file")
    ap.add_argument("--loop", action="store_true", help="loop a video file")
    ap.add_argument("--no-display", action="store_true", help="headless (no OpenCV window)")
    ap.add_argument("--detect-every", type=int, help="override detector frame interval")
    ap.add_argument("--threshold", type=float, help="override cosine similarity threshold")
    ap.add_argument("--gate-line", action="store_true", help="enable the virtual ENTRY/EXIT line")
    args = ap.parse_args()

    if args.source == "rtsp" and RTSP_PLACEHOLDER_MARKER in args.url:
        print("The RTSP URL is still the placeholder. Pass --url rtsp://... or edit config.RTSP_URL.\n"
              "To try the system right now:  python inference.py --source webcam")
        return 2
    if args.source == "file" and not args.path:
        print("--source file needs --path /path/to/video.mp4")
        return 2

    overrides = {}
    if args.detect_every:
        key = "file_detect_every_n" if args.source == "file" else "detect_every_n"
        overrides[key] = args.detect_every
    if args.threshold:
        overrides["similarity_threshold"] = args.threshold
    if args.gate_line:
        overrides["gate_line_enabled"] = True
    settings = dataclasses.replace(DEFAULT_SETTINGS, **overrides)

    store = Store()
    engine = FaceEngine(settings)
    target = {"rtsp": args.url, "webcam": args.index, "file": args.path}[args.source]
    reader = open_source(args.source, target, loop=args.loop)
    if reader.last_error and not reader.is_live:
        print(reader.last_error)
        return 1
    if reader.is_live and reader.last_error:
        print("[inference] warning:", reader.last_error, "\n[inference] will keep retrying ...")

    pipeline = GatePipeline(engine, store, settings, source_label=args.source,
                            is_file=args.source == "file")
    limiter = FpsLimiter(0 if args.source == "file" else settings.target_fps)
    print(f"[inference] source={reader.describe()} | enrolled={pipeline.gallery.size} | "
          f"detect every {pipeline.detect_every} frame(s)")
    if pipeline.gallery.size == 0:
        print("[inference] no students enrolled yet - every face will show as Unknown. Run enrollment.py.")

    frames = 0
    try:
        while True:
            ok, frame = reader.read()
            if not ok:
                if reader.is_live:
                    continue                      # grabber is reconnecting
                print("[inference] end of video")
                break
            out, info = pipeline.process(frame)
            frames += 1
            for ev in info["new_events"]:
                print("[LOGGED]", ev)
            if not args.no_display:
                cv2.imshow(WINDOW, out)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("[inference] q pressed - shutting down")
                    break
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break                          # window closed with the mouse
            limiter.wait()
    except KeyboardInterrupt:
        print("\n[inference] interrupted")
    finally:
        reader.release()
        pipeline.close()
        if not args.no_display:
            cv2.destroyAllWindows()
        print(f"[inference] stopped after {frames} frames; {pipeline.session_logged} attendance rows logged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
