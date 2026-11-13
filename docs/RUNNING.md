# Running the upgraded system

Three processes (plus the legacy Streamlit UI, which still works: `streamlit run dashboard.py`).

```bash
# 0. once, in your existing venv (pinned requirements.txt already installed)
pip install -r requirements-api.txt
python migrate_database.py            # additive PAD schema; backs up the DB to data/backups/ first
                                       # (the API also does this automatically on first start)

# 1. gate worker: owns the ONLY FaceEngine + PAD session; keeps the camera running independent of the browser
PYTHONPATH=. python -m backend.worker

# 2. API
PYTHONPATH=. uvicorn backend.app:app --host 127.0.0.1 --port 8000
#    first start prints a ONE-TIME SETUP TOKEN; open http://localhost:3000/login and create the first admin.

# 3. frontend
cd frontend && cp .env.example .env.local && npm install && npm run dev      # http://localhost:3000
```

Do not use `uvicorn --reload` for the worker. A second worker exits immediately (flock on `data/worker.lock`).
Do not use `uvicorn --workers N` for the API: the in-process rate limiter and worker link assume one process.

## Existing accounts
The legacy `users` table (salted SHA-256, default `admin123`) is **never used for login**. Its rows are copied to
`web_users` without a password and flagged `must_reset`. Sign in with the first-run setup admin, then use
Users -> "Temporary password" for each person, or "Create student accounts" for students (the old
"password = roll number" rule is gone). Argon2id, HTTP-only SameSite=Lax cookie, CSRF header, login rate limit.

## Turning anti-spoofing on (needs you - no weights are bundled)
1. `python -m venv /tmp/conv && . /tmp/conv/bin/activate && pip install torch onnx onnxruntime numpy`
2. `git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing /tmp/sfas`
3. Read `src/anti_spoof_predict.py`, `src/generate_patches.py`, `src/utility.py`, `LICENSE` in that clone and compare with
   `antispoof.py` / `data/models/antispoofing/MODELS.json` (crop scale 2.7 / 4.0, BGR, 0-255 not /255, 80x80, 3-class
   softmax, index 1 = real). Fix the manifest if anything differs.
4. `python tools/convert_minifas.py --repo /tmp/sfas --out data/models/antispoofing` (writes the two `.onnx` files and pins their SHA-256 in `MODELS.json`).
5. Back in the runtime venv: `python -m pytest tests/test_antispoof.py -q` (the real-model test stops being skipped),
   `python tools/pad_eval.py --benchmark`, then record a test set (guide inside `tools/pad_eval.py`) and run
   `python tools/pad_eval.py --live ... --spoof ...` to choose thresholds. Only then set `liveness_mode="minifas"`
   (Live page -> Tuning, or change the default in `config.py`).
Until then the default stays `"off"`, the UI shows "Anti-spoofing OFF", and PAD reports NOT_CONFIGURED.
In `minifas` mode with no valid weights, attendance is **rejected** (`pad_unconfigured_policy="reject"`) - never silently allowed.
