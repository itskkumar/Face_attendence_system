# Upgrade status - what is verified and what is not

Authored in a sandbox with **no network**: no PyPI/npm/GitHub, no insightface, no FastAPI, no Node packages, no camera.

## Done and verified (tests actually run: 112 passed, 5 skipped)
- Phase 1 audit + baseline (docs/PHASE1_AUDIT.md). Baseline in the sandbox: 42 passed / 3 skipped (+2 skipped files needing `av`/`streamlit`/`insightface`); the README's "48" must be re-checked in your pinned venv.
- `antispoof.py`: PADProvider/PADResult/NullPAD/MiniFASNetPAD, official-style crop (shift not squash), BGR 0-255 tensor, loader validation (HTML / sha256 / shapes / dummy softmax run), temporal `decide_pad`. No neutral fallback exists. Tests: `tests/test_antispoof.py` (ONNX session is SIMULATED; shape/dtype/range/channel order locked).
- Pipeline hooks only (PAD gate in `_quality_sample`, attendance gate in `_try_log`/`_log_deferred`, deferred path blocked without LIVE, re-verify spoof revoke + audit + flagged pad_events, `event_sink`, deferred-worker logging). Tests with a SIMULATED provider: LIVE passes, SPOOF/UNCERTAIN/NOT_CONFIGURED/ERROR block, deferred blocked (with an off-mode control proving the path is exercised), re-verify revokes, "no row without LIVE" in every state.
- Golden regression: `tests/golden_off_mode.json` was recorded from the ORIGINAL pipeline before any hook; the post-change pipeline reproduces it exactly with `liveness_mode="off"`.
- Additive migration (`pad_store.py`, `migrate_database.py`) tested on a copy of the shipped DB: every row intact, idempotent, backup made.
- Backend logic that does not need FastAPI: `backend/security.py` (Argon2 interface, sessions, CSRF, rate limit, legacy-user migration), `backend/services.py`, `backend/worker.py` (single instance lock, bounded queues, newest-frame-only, preview only when watched, one engine/PAD per process, enrollment RPC), `backend/worker_client.py` - tested, including a real authenticated localhost transport round-trip.
- `tools/pad_eval.py` metrics (APCER/BPCER/sweep) unit-tested on hand-computed numbers. `tools/check_frontend_routes.py`: all 40 frontend API calls have a matching backend route.

## Written but NEVER RUN (needs your machine)
- `backend/app.py` (FastAPI) - only syntax/mypy-name checked. `tests/test_backend_api.py` covers auth, CSRF, origin, role matrix, student scoping, pagination, rate limit, no-embeddings/no-credentials, WebSocket auth; it is skipped until `pip install -r requirements-api.txt`. Argon2 itself (`Argon2Hasher`) was never executed (tests use a fake hasher).
- The whole `frontend/` (Next.js): never installed, type-checked, linted, built or tested (`npm install && npm run typecheck && npm test && npm run build`). Expect to fix some type/lint errors. Its vitest tests were not run.
- Pinned versions in `requirements-api.txt` and `frontend/package.json` were not resolved against a registry.

## Not done / needs you
- **Real PAD weights**: none bundled; PAD is `NOT_CONFIGURED`, default `liveness_mode="off"`. Steps in docs/RUNNING.md. The preprocessing constants were written from memory of the official project and MUST be compared with its source (manifest says so).
- No real-model test, no phone-replay/printed-photo integration test, no before/after FPS or latency benchmark with `inference.py`, no CoreML-vs-CPU PAD benchmark (CPU is the default; `tools/pad_eval.py --benchmark` measures it). No accuracy numbers are claimed.
- The 48-test baseline in your pinned environment, the `test_webrtc_processor.py` file (needs `av`), insightface/streamlit-dependent tests.
- Legacy Streamlit UI untouched and still in the repo. Active-challenge/depth extension: interface only (`ChallengeProvider`).
- Student pages and user passwords: legacy SHA-256 users cannot log in to the new UI until an admin sets a temporary password.
- `bulk_import_students` (existing Store method) only updates existing students; the CSV import reports that honestly.
- Git: your two pre-existing uncommitted edits to `config.py`/`vision_math.py` were committed on the branch and then superseded. Pushing to the remote failed earlier (repo not authorized in the session).
