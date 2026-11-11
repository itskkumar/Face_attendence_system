# Phase 1 audit and baseline (branch feature/react-ui-and-pad)

## Baseline tests (this sandbox, before any change)
`python -m pytest tests -q --ignore=tests/test_webrtc_processor.py` -> **42 passed, 3 skipped**.
- Not the README's 48: `tests/test_webrtc_processor.py` cannot be collected (`av` missing).
- Skipped for missing packages: `insightface` (test_real_models, one in test_vision_math), `streamlit` (test_ui_smoke).
- Sandbox has numpy 2.5.3 / opencv 5.0, not the pinned 1.26.4 / 4.10. The 48-test baseline must be re-run in the pinned venv on your Mac.

## DB backup
`data/backups/attendance_system.pre-upgrade.db` (sha256 9a3cb4da...86, identical to the original).
Rows: students 3, face_templates 8, attendance_logs 35, users 3, system_health 3, audit_logs 0, meta 1.

## Section 2 findings, verified from code
1. CONFIRMED: `data/models/antispoofing/minifas_v2.onnx` is an HTML page (`file` reports HTML document).
2. CONFIRMED: `pipeline.py` never references `MiniFASLiveness`; only `fft_moire_score` when `liveness_mode == "fft_experimental"`. Default is "off".
3. CONFIRMED: `MiniFASLiveness.predict` has a failure fallback (vision_math.py ~L296-305, error path) that returns neutral scores.
4. CONFIRMED: config.py comments still claim "~95% accuracy"; preprocessing is unverified.
5. CONFIRMED: `_deferred_worker` -> `_log_deferred` -> `logger.maybe_log` with no liveness check; `_try_log` has none; `_reverify` cannot revoke; "spoof" only set from FFT before embeddings exist (pipeline.py ~L294-298).
6. Users table: 3 users (admin, karan, arjun) with salted SHA-256 hashes (`salt:hash`).
7. `process()` / `inference.py` seam present.

## Repo state to be aware of
- `git status` before branching: `config.py` and `vision_math.py` have UNCOMMITTED edits (the MiniFAS config fields and the `MiniFASLiveness` class), plus untracked `data/models/` and `.claude/`. They were left as-is, not committed.

## Blockers in this sandbox (network is closed)
curl to GitHub, npm registry and PyPI all fail; pip cannot find fastapi. Not installed: insightface, faiss, av, streamlit, fastapi, argon2. Consequences:
- Official MiniFASNet weights cannot be downloaded here -> PAD stays NOT_CONFIGURED until you supply them.
- FastAPI/Next.js can be written but not run or tested here.
