"""
pad_eval.py - measure the PAD model on YOUR data. Reports only what it measures.

  python tools/pad_eval.py --live data/pad_eval/live --spoof data/pad_eval/spoof [--threshold 0.7] [--csv out.csv]
  python tools/pad_eval.py --benchmark            # CPU vs CoreML latency of the PAD session (needs weights)

Folders hold images (jpg/png) or videos (mp4/mov/avi; every --every-th frame is used). Faces are found
with the production detector (needs insightface); use --whole-image-is-face only for pre-cropped faces
(then the official 2.7x/4.0x context crop cannot be reproduced, results are not comparable).

  APCER = attacks accepted as live / all attacks        (security error)
  BPCER = live faces rejected / all live faces          (usability error)
A sample is "accepted as live" when its real-probability >= threshold.
These are PER-FRAME numbers; the pipeline additionally needs several agreeing observations per track
(pad_min_obs), so deployed error is expected to differ. No figures are quoted here: run it on real data.

RECORDING GUIDE (small but honest test set at the real gate, same camera, same mounting)
  live/  : 10+ different people, walking in normally; morning/evening/backlit; glasses on/off; near and far
  spoof/ : phone replay of each person (full brightness and dimmed), tablet replay, printed A4 photo
           (glossy and matte), photo held by hand and bent, photo on a stick; different distances,
           angles, and lighting; include the exact attacks you worry about
  Keep people in live/ and spoof/ disjoint from any threshold tuning set. 100 frames per class is a
  minimum to see anything; fewer than that gives meaningless percentages.
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMG = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VID = {".mp4", ".mov", ".avi", ".mkv"}


def apcer_bpcer(live_scores, spoof_scores, threshold):
    """Error rates for real-probability scores. Empty classes give None (not 0)."""
    apcer = (sum(s >= threshold for s in spoof_scores) / len(spoof_scores)) if spoof_scores else None
    bpcer = (sum(s < threshold for s in live_scores) / len(live_scores)) if live_scores else None
    return apcer, bpcer


def sweep(live_scores, spoof_scores, steps=19):
    out = []
    for i in range(1, steps + 1):
        t = i / (steps + 1)
        a, b = apcer_bpcer(live_scores, spoof_scores, t)
        out.append((round(t, 3), a, b))
    return out


def _fmt(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def iter_frames(folder, every):
    import cv2
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            if ext in IMG:
                img = cv2.imread(path)
                if img is not None:
                    yield path, img
            elif ext in VID:
                cap, i = cv2.VideoCapture(path), 0
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    if i % every == 0:
                        yield f"{path}#{i}", frame
                    i += 1
                cap.release()


def score_folder(folder, label, pad, detect, every, whole):
    rows, skipped = [], 0
    for ident, frame in iter_frames(folder, every):
        if whole:
            h, w = frame.shape[:2]
            boxes = [(0, 0, w, h)]
        else:
            dets = detect(frame)
            boxes = [max(dets, key=lambda d: d.score).bbox] if dets else []
        if not boxes:
            skipped += 1
            continue
        r = pad.observe(frame, boxes[0])
        if not r.valid:
            skipped += 1
            print(f"  skip {ident}: {r.state} {r.reason}")
            continue
        rows.append((label, ident, r.real_prob, r.latency_ms))
    return rows, skipped


def benchmark():
    import numpy as np
    import antispoof
    from face_engine import available_candidates
    img = np.random.default_rng(0).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    for label in ["cpu"] + [l for l, _ in available_candidates("auto") if l != "cpu"]:
        pad = antispoof.MiniFASNetPAD(provider_label=label)
        if pad.health()["state"] != "READY":
            print(f"{label}: {pad.health()['state']} - {pad.health()['reason']}")
            return 1
        for _ in range(5):
            pad.observe(img, (500, 200, 700, 450))
        t = [pad.observe(img, (500, 200, 700, 450)).latency_ms for _ in range(100)]
        print(f"{label}: median {np.median(t):.2f} ms, p95 {np.percentile(t, 95):.2f} ms over 100 runs")
    print("Set PAD_PROVIDER=<label> to use a non-CPU provider.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live"); ap.add_argument("--spoof")
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--every", type=int, default=5, help="use every Nth video frame")
    ap.add_argument("--csv", default="pad_eval_scores.csv")
    ap.add_argument("--whole-image-is-face", action="store_true")
    ap.add_argument("--benchmark", action="store_true")
    a = ap.parse_args()
    if a.benchmark:
        return benchmark()
    if not (a.live and a.spoof):
        ap.error("--live and --spoof folders are required (record them first, see the guide in this file)")

    import antispoof
    pad = antispoof.MiniFASNetPAD()
    if pad.health()["state"] != "READY":
        print("PAD is", pad.health()["state"], "-", pad.health()["reason"])
        return 1
    detect = None
    if not a.whole_image_is_face:
        from config import DEFAULT_SETTINGS
        from face_engine import FaceEngine
        detect = FaceEngine(DEFAULT_SETTINGS).detect
    live, sl = score_folder(a.live, "live", pad, detect, a.every, a.whole_image_is_face)
    spoof, ss = score_folder(a.spoof, "spoof", pad, detect, a.every, a.whole_image_is_face)
    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["label", "sample", "real_prob", "latency_ms"]); w.writerows(live + spoof)
    ls, ss_ = [r[2] for r in live], [r[2] for r in spoof]
    print(f"live samples: {len(ls)} (skipped {sl}) | spoof samples: {len(ss_)} (skipped {ss})")
    ap_, bp = apcer_bpcer(ls, ss_, a.threshold)
    print(f"threshold {a.threshold}: APCER {_fmt(ap_)} | BPCER {_fmt(bp)}")
    print("threshold sweep (threshold, APCER, BPCER):")
    for t, x, y in sweep(ls, ss_):
        print(f"  {t:.2f}  {_fmt(x):>7}  {_fmt(y):>7}")
    print("scores written to", a.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
