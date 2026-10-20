"""
benchmark.py - measure which ONNXRuntime provider is fastest on THIS machine.

  python benchmark.py                  # compares CPU vs CoreML variants (on a Mac)
  python benchmark.py --image me.jpg   # use your own image (otherwise InsightFace's sample)

The winner is saved to data/provider_choice.json and used automatically by
every tool when provider_mode == "auto". Run it once after installing.
"""
import argparse
import json
import statistics
import time

import cv2
import numpy as np

from config import DEFAULT_SETTINGS, PROVIDER_CACHE_PATH
from face_engine import COREML_DEFAULT, COREML_FAST, CPU_SPEC, FaceEngine, available_candidates


def sample_image(path):
    if path:
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"cannot read {path}")
        return img
    try:
        from insightface.data import get_image
        return get_image("t1")
    except Exception:
        rng = np.random.default_rng(0)
        return (rng.random((720, 1280, 3)) * 255).astype(np.uint8)


def bench(spec, img, runs):
    try:
        eng = FaceEngine(DEFAULT_SETTINGS, candidates=[spec])
    except Exception as exc:
        return None, f"failed: {str(exc).splitlines()[-1][:90]}"
    crop = np.random.default_rng(1).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    for _ in range(3):
        eng.detect(img); eng.embed_aligned(crop)
    det, rec = [], []
    for _ in range(runs):
        t = time.perf_counter(); eng.detect(img); det.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter(); eng.embed_aligned(crop); rec.append((time.perf_counter() - t) * 1000)
    return (statistics.median(det), statistics.median(rec)), "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image"); ap.add_argument("--runs", type=int, default=20)
    args = ap.parse_args()
    img = sample_image(args.image)
    specs = [s for s in (CPU_SPEC, COREML_FAST, COREML_DEFAULT) if s in available_candidates("coreml") or s == CPU_SPEC]
    print(f"image {img.shape[1]}x{img.shape[0]}, {args.runs} runs each (median ms)\n")
    print(f"{'provider config':26s} {'detect':>9s} {'embed':>9s} {'sum':>9s}")
    results = {}
    for spec in specs:
        res, note = bench(spec, img, args.runs)
        if res is None:
            print(f"{spec[0]:26s} {note}")
            continue
        results[spec[0]] = res
        print(f"{spec[0]:26s} {res[0]:9.1f} {res[1]:9.1f} {sum(res):9.1f}")
    if not results:
        raise SystemExit("no provider worked")
    best = min(results, key=lambda k: sum(results[k]))
    with open(PROVIDER_CACHE_PATH, "w") as f:
        json.dump({"choice": best, "results_ms": results}, f, indent=2)
    print(f"\nfastest: {best}  -> saved to {PROVIDER_CACHE_PATH}")


if __name__ == "__main__":
    main()
