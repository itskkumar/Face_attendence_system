"""
config.py - central configuration.

Every tunable lives in the frozen `Settings` dataclass so the CLI tools, the
Streamlit pages and the tests all share one source of truth. The Streamlit
sidebar builds modified copies with `dataclasses.replace(...)`, so tuning in the
UI never mutates global state.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# --- Environment tweaks (must be set before cv2 opens any capture device) -----
# Stops OpenCV probing for Orbbec depth cameras (the noisy "OBSENSOR" log lines
# you see on macOS when camera access is denied).
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")
# RTSP over TCP with low latency: far fewer corrupted frames than UDP.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay",
)

# --- Paths --------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.environ.get("ATTENDANCE_DB", os.path.join(DATA_DIR, "attendance_system.db"))
PROVIDER_CACHE_PATH = os.path.join(DATA_DIR, "provider_choice.json")

# Anti-spoofing model path
ANTISPOOFING_MODEL_DIR = os.path.join(DATA_DIR, "models", "antispoofing")
MINIFAS_ONNX_PATH = os.path.join(ANTISPOOFING_MODEL_DIR, "minifas_v2.onnx")

# --- Video sources ------------------------------------------------------------
# Placeholder RTSP URL - replace with your gate camera, or pass --url on the CLI.
RTSP_URL = "rtsp://username:password@192.168.1.100:554/stream1"
RTSP_PLACEHOLDER_MARKER = "username:password@"
DEFAULT_SOURCE = "rtsp"          # rtsp | webcam | file
WEBCAM_INDEX = 0

DATE_FMT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class Settings:
    # ---- Hardware / model ----------------------------------------------------
    # "auto": use the provider chosen by benchmark.py if present, else CoreML
    #         with automatic CPU fallback.  "coreml" | "cpu" force a choice.
    provider_mode: str = "auto"
    det_size: int = 640              # detector input (square). Larger = finds smaller faces, slower
    det_low_thresh: float = 0.30     # detector keeps boxes >= this (low ones feed ByteTrack stage 2)
    process_width: int = 960         # frames wider than this are downscaled before detection

    # ---- Real-time scheduling ------------------------------------------------
    detect_every_n: int = 2          # live sources: run the detector every Nth frame
    file_detect_every_n: int = 1     # uploaded/recorded video: every frame (max accuracy)
    target_fps: int = 25             # live loops sleep to stay under this (thermal control)
    display_width: int = 960

    # ---- Tracking (ByteTrack-style) -----------------------------------------
    track_high_thresh: float = 0.50
    track_low_thresh: float = 0.10
    track_new_thresh: float = 0.60
    track_match_thresh: float = 0.80   # max (1 - IoU) for stage-1 matches
    track_max_age: int = 30            # frames a lost track survives
    track_min_hits: int = 2            # detections needed before a track is shown

    # ---- Quality gates (a face must pass these before ArcFace runs) ---------
    min_det_score: float = 0.60
    min_face_px: int = 56              # face box width in original-resolution pixels
    min_blur_var: float = 15.0         # LIVE: variance of Laplacian on the aligned 112x112 crop
    enroll_min_blur_var: float = 30.0  # ENROLMENT photos must be sharper than live CCTV frames
    min_pose_score: float = 0.45       # 1.0 = frontal; falls as the head turns (real group photo: 0.16-0.93)

    # ---- Recognition ---------------------------------------------------------
    similarity_threshold: float = 0.45  # cosine similarity needed to accept a match
    similarity_margin: float = 0.05     # best must beat 2nd-best student by this much
    min_votes: int = 3                  # quality keyframes aggregated before locking identity
    max_attempts: int = 8               # keyframes without a match -> "Unknown"
    early_accept_sim: float = 0.65      # strong single-frame match may lock after 2 votes
    rec_interval_frames: int = 4        # min frames between embeddings for one track
    reverify_interval_frames: int = 60  # identified tracks are re-checked this often
    unknown_retry_frames: int = 90      # "Unknown" tracks get a fresh attempt this often

    # ---- Attendance ----------------------------------------------------------
    cooldown_seconds: int = 5 * 60      # same person is logged at most once per window
    default_direction: str = "ENTRY"

    # ---- Virtual gate line (direction + optional crossing requirement) ------
    gate_line_enabled: bool = False
    gate_line_orientation: str = "horizontal"   # horizontal | vertical
    gate_line_ratio: float = 0.55               # position as a fraction of frame height/width
    gate_entry_direction: str = "down"          # down|up|right|left = which way counts as ENTRY
    require_gate_crossing: bool = False         # True: log only after the line is crossed

    # ---- Liveness / presentation-attack detection (PAD) ---------------------
    # "off"              : no liveness check (legacy behaviour; the UI shows an "Anti-spoofing OFF" warning)
    # "fft_experimental" : legacy FFT moire heuristic. UNVALIDATED, can never mean "live".
    # "minifas"          : pretrained MiniFASNet ONNX models, see antispoof.py and
    #                      data/models/antispoofing/MODELS.json. Attendance needs pad_state == LIVE.
    liveness_mode: str = "off"
    liveness_min_score: float = 0.35            # fft_experimental only

    # PAD tuning (only used when liveness_mode == "minifas"). STARTING POINTS, not validated:
    # calibrate with tools/pad_eval.py on data recorded at your own gate.
    pad_window: int = 5                         # observations kept per track
    pad_min_obs: int = 3                        # valid observations needed before LIVE/SPOOF can be decided
    pad_real_threshold: float = 0.70            # a frame counts as "real" when real_prob >= this
    pad_spoof_threshold: float = 0.70           # a frame counts as "attack" when spoof_prob >= this
    pad_max_observation_seconds: float = 8.0    # after this long without LIVE the track is flagged REVIEW REQUIRED
    pad_unconfigured_policy: str = "reject"     # "reject" | "manual_review" when PAD is NOT_CONFIGURED / ERROR
    pad_observation_interval_frames: int = 2    # min detector-frames between PAD observations for one track
    pad_edge_margin_px: int = 4                 # faces touching the frame edge give no PAD observation

    # ---- Deferred recognition (for fast-moving persons) ---------------------
    enable_deferred_recognition: bool = True    # process tracks that left frame while pending
    buffer_crops_for_deferred: int = 5          # keep best N frame crops per track
    deferred_min_embeddings: int = 2            # need at least this many to attempt deferred ID

    # ---- Snapshots (save face/person crops when logging attendance) ---------
    save_snapshots: bool = False                # save face and person crops on attendance log

    # ---- FAISS HNSW vector search (O(log N) approximate nearest neighbor) ---
    enable_faiss_hnsw: bool = True              # Use FAISS HNSW index if available, fallback to NumPy
    faiss_hnsw_m: int = 32                      # HNSW graph connectivity parameter
    faiss_ef_construction: int = 64             # Build-time search depth
    faiss_ef_search: int = 32                   # Query-time search depth


DEFAULT_SETTINGS = Settings()
