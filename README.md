<img width="1463" height="833" alt="Screenshot 2026-10-20 at 9 39 55 PM" src="https://github.com/user-attachments/assets/83604afb-c8fc-4f26-b0d8-e2ccdb19527d" />
# Real-Time Face Recognition, Attendance & Counting System — v2

Gate-camera attendance for a college: detects **every** face in view (groups of 3+ are fine), tracks each
person, recognises them, and logs one attendance row per person per cooldown window. Built for an
**Apple-Silicon Mac** (ONNXRuntime + CoreML), with a live **Streamlit** dashboard.

```
Camera / MP4 / browser webcam
        │
        ▼
 FrameGrabber (thread keeps only the NEWEST frame → no RTSP lag; auto-reconnect)
        │
        ▼
 SCRFD-10G face + 5-landmark detector   ── every Nth frame (Kalman-predicted boxes in between)
        │
        ▼
 ByteTrack-style tracker: Kalman filter + Hungarian assignment + Mahalanobis gating,
 2-stage association (low-confidence boxes rescue blurred/occluded faces)
        │            one persistent ID per person
        ▼
 Quality gate per track: face size · detector score · pose · blur (Laplacian variance)
        │            only GOOD frames ("keyframes") continue
        ▼
 Umeyama SVD alignment → 112×112 → ArcFace-R50 → 512-d unit vector
        │
        ▼
 Voting: quality-weighted average of several keyframes → cosine similarity vs all templates
         (multi-template, best-vs-second-best margin) → identity locked only when keyframes agree
        │                         └─ no match after N keyframes → red "Unknown" (never logged)
        ▼
 AttendanceLogger: in-memory last_seen_dict + atomic SQLite check → one row per cooldown (default 5 min)
        │             identified tracks are periodically RE-VERIFIED (guards against track-ID swaps)
        ▼
 SQLite (WAL)  ◄──────────────  Streamlit dashboard (auto-refresh 3 s) / CSV export
```

## Quick start (Apple Silicon Mac)

```bash
# 1. native arm64 Python 3.10-3.12 (3.11 recommended; NOT 3.13/3.14 - ML wheels are missing)
python3.11 -c "import platform; print(platform.machine())"        # must print arm64
xcode-select --install                                           # once

# 2. environment
cd face_attendance_v2
python3.11 -m venv venv && source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt            # first run later downloads ~280 MB of models

# 3. (recommended, once) find the fastest ONNXRuntime provider on YOUR machine
python benchmark.py

# 4. run
python database_setup.py                    # optional; every tool creates the DB if missing
streamlit run dashboard.py                  # dashboard + Live Feed + Enrollment pages in the sidebar
```

Then in the browser: **Enrollment** page → enrol yourself (3-5 photos, turn your head slightly between
shots) → **Live Feed** page → pick a source → watch the box turn green and the **Dashboard** count go up.

### Command-line tools (same engine, no browser)

```bash
python enrollment.py                                         # guided webcam capture (5 poses, auto-capture)
python enrollment.py --name "Asha Kumari" --roll 23CS24 --folder ./photos/asha   # from photos
python inference.py --source webcam                          # live webcam, OpenCV window, q to quit
python inference.py --source rtsp --url rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101
python inference.py --source file --path gate_clip.mp4 --no-display              # recorded CCTV clip
```
Run `inference.py` in one terminal and `streamlit run dashboard.py` in another: the dashboard shows what
the engine logs, live. (Switching Streamlit *pages* stops a stream that page is running — for a permanent
gate deployment run `inference.py` and keep the dashboard open in a browser tab.)

## What the Live Feed page offers

| Source | Notes |
|---|---|
| Upload a video (CCTV `.mp4`) | every frame analysed, nothing dropped; optional annotated-video download |
| Video file by path | same, without the upload-size round trip |
| Server webcam | the camera of the machine running Streamlit |
| RTSP camera | threaded grabber, TCP transport, reconnect with backoff |
| Browser webcam (WebRTC) | the visitor's own camera; works on `localhost`/HTTPS; a public site may need a TURN server |

The sidebar exposes the main thresholds (similarity, sharpness, frontal-ness, detect interval, cooldown,
virtual ENTRY/EXIT line) so you can tune live against your own camera.

## Tuning for your camera (important)

All defaults live in `config.py → Settings`. They are sensible starting points, **not** calibrated to your
camera:

* **Similarity threshold (0.45)** — on real test faces, *different* people scored −0.09…0.20, while the
  same person (augmented copies of one photo, video-compressed) scored 0.58–0.97. That last range is
  optimistic: a *different* photo of the same person, e.g. CCTV vs. enrolment, will usually score lower.
  Raise the threshold if a stranger is accepted; lower it if enrolled people stay "Unknown". Calibrate on
  your own enrolled students.
* **Sharpness gate (15 live / 30 enrolment)** — the amber label says *blurry* when a face is rejected;
  lower the slider for soft CCTV streams.
* **Frontal-ness gate (0.45)** — in a normal group photo 3 of 6 faces scored below 0.55, so don't set it high.
* **Detect every N frames** — raise it (3-4) if the Air gets warm; boxes still update every frame.
* **Camera placement** — face ≥ ~80-100 px wide, camera slightly above eye level, enable the camera's WDR
  for backlit gates.

## Tests

```bash
pip install pytest
python -m pytest tests -q          # 48 tests, ~1 min on CPU
```

| Area | What is verified |
|---|---|
| Math | Umeyama recovers a known transform, is least-squares optimal, **matches InsightFace's own reference transform**; blur/pose metrics |
| Tracker | stable IDs for 3 people walking together, with 25 % missed detections, with low-confidence frames, with crossing paths; ghost-track pruning |
| Database | multi-template matching, margin rule, duplicate-identity refusal, **cooldown atomic under 16 concurrent writers**, today-only counts, restart hydration |
| Pipeline logic (scripted fake models) | group of 4 (3 known + 1 unknown), cooldown expiry, blur/size gating, Unknown handling, **ID-swap re-verification**, ENTRY/EXIT line, live enrolment pickup, no box flicker when the detector is skipped |
| **Real models** | enrols 3 people from a real group photo, runs a compressed video: the 3 are logged exactly once, 1 stranger is "Unknown", 2 turned-away faces are *not judged* |
| UI | every page renders; a video file is processed through the Live Feed page; the WebRTC processor handles real `av.VideoFrame`s end-to-end |

All of the above ran on Linux x86 / Python 3.12 with the same pinned versions you install.

**Not testable here (no Mac, no camera, no display):** CoreML acceleration and real FPS on your M4, a
physical webcam, a real RTSP camera, the OpenCV preview window (`cv2.imshow`), and the in-browser WebRTC
handshake. `benchmark.py` measures the first on your machine; the others fail with explicit, actionable
messages. Expect to spend a few minutes tuning thresholds against your own camera.

## Known limitations (read before demoing)

* **No real anti-spoofing.** A printed photo or phone screen can be accepted. The optional *FFT liveness*
  switch is an **unvalidated heuristic** and is off by default; production use needs a trained model
  (e.g. MiniFASNet).
* Two people whose boxes overlap **exactly** can swap track IDs — any motion-only tracker can. The pipeline
  re-verifies identities every ~2 s and resets a track after two disagreements, so a swap self-corrects.
* Recognition is only as good as enrolment: use 3-5 sharp photos at slightly different angles.
* Masks, heavy sunglasses, very low light and faces < ~60 px wide degrade accuracy.
* On-screen labels use OpenCV fonts (ASCII only): accents are folded and non-Latin names show as `?`.
  Tables and CSV keep the full Unicode name.
* The detector in InsightFace's `buffalo_l` pack is **SCRFD-10G** (the Python class that runs it is named
  `RetinaFace`). Say "SCRFD" if asked which detector this uses.
* Face data is biometric personal data: get consent, restrict access to `data/attendance_system.db`, and
  follow your institution's policy.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Could not find a version that satisfies onnxruntime` | you are on Python 3.13/3.14 → recreate the venv with `python3.11` |
| Camera denied / `OpenCV: camera failed to properly initialize` | System Settings → Privacy & Security → Camera → enable your terminal → **quit and reopen** it. The Enrollment page uses the browser camera instead |
| `streamlit-webrtc` import error / page crash after upgrading | keep `streamlit==1.45.1` (newer Streamlit dropped Tornado) |
| `pyarrow requires NumPy 2` | keep `pyarrow<21` and `numpy==1.26.4` as pinned |
| RTSP black/laggy | test the URL in VLC; use the camera's *sub-stream*; the grabber already forces TCP |
| Everyone is "Unknown" | enrol first; lower the similarity slider a little; check lighting and the amber hint text |
| Warm MacBook Air | raise *Detect every N frames*, lower `target_fps`, run `benchmark.py` |

## Files

| File | Role |
|---|---|
| `dashboard.py`, `pages/1_Live_Feed.py`, `pages/2_Enrollment.py`, `ui_common.py`, `webrtc_processor.py` | Streamlit app |
| `inference.py`, `enrollment.py`, `database_setup.py`, `benchmark.py` | command-line tools |
| `pipeline.py` | detection → tracking → quality gate → voting → logging → drawing |
| `tracker.py`, `vision_math.py` | Kalman/ByteTrack tracker; Umeyama, blur, pose, FFT utilities |
| `face_engine.py` | InsightFace wrapper, CoreML provider selection + fallback |
| `database.py`, `attendance.py`, `enrollment_core.py`, `video_sources.py`, `config.py` | storage, cooldown logger, enrolment checks, readers, settings |
