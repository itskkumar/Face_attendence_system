"""
enrollment.py - register a student (Module A).

Three ways to run it:

  python enrollment.py                                   # interactive, guided webcam capture
  python enrollment.py --name "Asha Kumari" --roll 23CS24 # webcam, no prompts
  python enrollment.py --name "Asha Kumari" --roll 23CS24 --images a.jpg b.jpg c.jpg
  python enrollment.py --name "Asha Kumari" --roll 23CS24 --folder ./photos/asha

Several samples per person (different poses) make recognition much more robust
than a single photo. Each sample must pass quality gates (one face, big enough,
sharp). A face already enrolled under another roll number is refused.
"""
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np

from config import DEFAULT_SETTINGS, WEBCAM_INDEX
from database import Store
from enrollment_core import analyze_face_for_enrollment
from face_engine import FaceEngine
from video_sources import open_source

STAGES = ["Look straight at the camera", "Turn your head slightly LEFT",
          "Turn your head slightly RIGHT", "Tilt your chin slightly UP",
          "Tilt your chin slightly DOWN"]


def collect_from_images(engine, paths):
    samples = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            print(f"  [skip] cannot read {p}")
            continue
        sample, reason = analyze_face_for_enrollment(engine, img, DEFAULT_SETTINGS)
        if sample is None:
            print(f"  [skip] {os.path.basename(p)}: {reason}")
        else:
            print(f"  [ok]   {os.path.basename(p)} (sharpness {sample.blur:.0f})")
            samples.append(sample)
    return samples


def collect_from_webcam(engine, index):
    reader = open_source("webcam", index)
    if reader.last_error:
        print("\n[enrollment] " + reader.last_error)
        reader.release()
        return []
    samples, stage, stable, last_grab = [], 0, 0, 0.0
    print("\nGuided capture: follow the on-screen instruction. Press 'q' to cancel.\n")
    try:
        while stage < len(STAGES):
            ok, frame = reader.read()
            if not ok:
                print("[enrollment] camera stopped delivering frames")
                break
            sample, reason = analyze_face_for_enrollment(engine, frame, DEFAULT_SETTINGS)
            stable = stable + 1 if sample is not None else 0
            if stable >= 4 and time.time() - last_grab > 0.8:      # held steady -> auto-capture
                samples.append(sample)
                stage += 1
                stable, last_grab = 0, time.time()
                print(f"  captured {stage}/{len(STAGES)} (sharpness {sample.blur:.0f})")
            view = frame.copy()
            msg = STAGES[stage] if stage < len(STAGES) else "Done"
            cv2.putText(view, f"[{len(samples)}/{len(STAGES)}] {msg}", (16, 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
            if sample is None:
                cv2.putText(view, reason, (16, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 255), 2, cv2.LINE_AA)
            cv2.imshow("Enrollment - press q to cancel", view)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("[enrollment] cancelled")
                return []
    finally:
        reader.release()
        cv2.destroyAllWindows()
    return samples


def main():
    ap = argparse.ArgumentParser(description="Enrol a student")
    ap.add_argument("--name"); ap.add_argument("--roll")
    ap.add_argument("--images", nargs="+"); ap.add_argument("--folder")
    ap.add_argument("--camera", type=int, default=WEBCAM_INDEX)
    ap.add_argument("--append", action="store_true", help="add templates instead of replacing")
    args = ap.parse_args()

    name = args.name or input("Full name: ").strip()
    roll = args.roll or input("Roll number: ").strip()
    if not name or not roll:
        sys.exit("Name and roll number are required.")

    store = Store()
    engine = FaceEngine(DEFAULT_SETTINGS)

    paths = list(args.images or [])
    if args.folder:
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            paths += glob.glob(os.path.join(args.folder, ext))
    samples = collect_from_images(engine, paths) if paths else collect_from_webcam(engine, args.camera)

    if not samples:
        sys.exit("No usable face samples - nothing saved.")
    embs = [s.embedding for s in samples]
    dup = store.find_duplicate_identity(embs, roll)
    if dup:
        sys.exit(f"Refused: this face already matches {dup[1]} ({dup[0]}) with similarity {dup[2]:.2f}.")
    sid, n = store.add_student(roll, name, embs, [s.quality for s in samples],
                               mode="append" if args.append else "replace")
    print(f"\n[enrollment] saved {name} ({roll.upper()}) with {n} template(s). Inference picks it up live.")


if __name__ == "__main__":
    main()
