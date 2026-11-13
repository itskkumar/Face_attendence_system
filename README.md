# Face Attendance System
<img width="1470" height="835" alt="Screenshot 2026-11-13 at 5 34 57 PM" src="https://github.com/user-attachments/assets/8f816f5c-96b7-48d8-b236-2b54e235ea2a" />


Camera-based attendance with face recognition and anti-spoofing, a FastAPI backend and a React web app.

- **Detection + recognition:** InsightFace `buffalo_l` (SCRFD-10G detector, ArcFace `w600k_r50` embeddings) on ONNX Runtime
- **Tracking:** ByteTrack-style tracker (Kalman filter, Hungarian matching)
- **Matching:** cosine similarity with a margin rule, multi-template per student, FAISS HNSW or NumPy gallery
- **Anti-spoofing (presentation-attack detection):** pretrained MiniFASNet (Silent-Face-Anti-Spoofing) running as an independent gate
- **Web app:** Next.js + React + TypeScript, glassmorphism UI, live camera page, enrollment, analytics, admin tools
- **API:** FastAPI + WebSocket, role-based access (admin / operator / student)
- **Legacy UI:** the original Streamlit app (`dashboard.py`, `pages/`) is still in the repo

> Biometric data warning: face images and templates are personal data. Read [Privacy](#privacy-and-security) before using this with real people.

---

## How it works

```
 Camera / RTSP / file / browser webcam
              |
      [ Gate worker process ]  one FaceEngine + one PAD session
        SCRFD detect -> track -> quality gates -> ArcFace embed -> match
                                    |
                           MiniFASNet PAD gate (liveness)
              |
   attendance written only if identity is verified AND the face is LIVE
              |
 SQLite  <--  [ FastAPI ]  <--REST + WebSocket-->  [ Next.js web app ]
```

Recognition says **who** the person is. Anti-spoofing says **whether a real face is present**. In `minifas` mode no code
path (immediate lock, deferred/fast-moving, retry, re-verify) writes attendance unless the track's PAD state is `LIVE`.
`UNCERTAIN`, `NOT_CONFIGURED` and `ERROR` never count as live. If a track that was already identified later reads as a
spoof, further logging for it stops, an audit entry and a flagged `pad_events` row are written, and the saved attendance row
is kept.

## Repository layout

| Path | Purpose |
|---|---|
| `face_engine.py`, `tracker.py`, `vision_math.py`, `database.py` | recognition core (detector, tracker, alignment, gallery/matching, SQLite store) |
| `pipeline.py` | per-frame decision logic (quality gates, voting, cooldown, gate line, PAD hooks) |
| `antispoof.py`, `pad_store.py` | MiniFASNet PAD module and its database helpers |
| `backend/` | FastAPI app, gate worker process, auth, services |
| `frontend/` | Next.js web app |
| `tools/` | `convert_minifas.py` (weights to ONNX), `pad_eval.py` (APCER/BPCER measurement) |
| `tests/` | pytest suite (including simulated PAD tests and a golden regression with liveness off) |
| `dashboard.py`, `pages/` | legacy Streamlit UI |
| `docs/` | API contract, running guide, upgrade status |
| `data/` | database, models, camera config (mostly git-ignored) |

## Requirements

- macOS or Linux, **Python 3.11 or 3.12** (the pinned `numpy==1.26.4` / `opencv-python==4.10.0.84` do not install on 3.13+)
- Node.js 20 or newer
- Internet on first run (InsightFace downloads `buffalo_l`)
- A webcam, RTSP camera, or video file

## Setup

```bash
git clone https://github.com/itskkumar/Face_attendence_system.git
cd Face_attendence_system
git checkout feature/react-ui-and-pad        # or main, once merged

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-api.txt pytest
python -m pytest tests -q -rs
```

Frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
```

## Anti-spoofing weights (one-time)

The pretrained weights are not stored in git as PyTorch files; convert them to ONNX once. This uses a separate throw-away
virtual environment, because it needs torch and the runtime environment stays torch-free.

```bash
python3.12 -m venv /tmp/conv && source /tmp/conv/bin/activate
pip install torch onnx onnxruntime numpy
git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing /tmp/sfas
python tools/convert_minifas.py --repo /tmp/sfas --out data/models/antispoofing
deactivate
```

This writes two `.onnx` files and pins their SHA-256 in `data/models/antispoofing/MODELS.json`. The loader refuses any
file that is not a valid model matching the manifest (HTML pages, wrong hash, wrong shapes) and reports `ERROR` or
`NOT_CONFIGURED` instead of a score. The preprocessing follows the official project: crop at scale 2.7 / 4.0 around the
face box (shifted, not squashed), 80x80, BGR, values 0-255 (not divided by 255), 3-class softmax, class 1 = real.

## Run

Use three terminals, in this order. From the project folder with the venv active:

```bash
# 1. gate worker: owns the camera and the models
PYTHONPATH=. python -m backend.worker

# 2. API (prints a one-time setup token on first start)
PYTHONPATH=. uvicorn backend.app:app --host 127.0.0.1 --port 8000

# 3. website
cd frontend && npm run dev
```

Open <http://localhost:3000>. On first run enter the setup token from terminal 2 and create the admin account. There are
no default credentials.

To turn anti-spoofing on, open **Live**, set the liveness mode to `minifas` in the tuning panel. The default stays `off`
until you have validated the model on your own camera.

## Accounts and roles

| Role | Can do |
|---|---|
| `admin` | everything: live control, enrollment, students, users, cameras, inspector, audit |
| `operator` | read-only monitoring: dashboard, search, live preview, security alerts |
| `student` | only their own attendance, profile and summary |

- Students are enrolled in **Enrollment**. A login account is separate: create it in **Users** with "Create student accounts".
  A one-time temporary password is shown once and must be changed at first sign-in.
- Roles are enforced on the server for every route and WebSocket; the UI only hides things.
- Passwords use Argon2id; sessions are server-side with an HTTP-only SameSite cookie, CSRF header, and login rate limiting.
- Accounts migrated from the old Streamlit `users` table have no password until an admin sets a temporary one.

## Evaluating anti-spoofing on your camera

No accuracy figure is claimed by this project. Measure it:

1. Record `live/` (real people, varied lighting, distance, glasses) and `spoof/` (phone replay, tablet, printed photo) at the real gate.
2. Run:
   ```bash
   python tools/pad_eval.py --live data/pad_eval/live --spoof data/pad_eval/spoof
   python tools/pad_eval.py --benchmark     # CPU vs CoreML latency
   ```
3. It prints **APCER** (attacks accepted as live), **BPCER** (real faces rejected), and a threshold sweep. Choose
   `pad_real_threshold` / `pad_spoof_threshold` in `config.py` from your own data.

Keep recordings out of git (`data/pad_eval/` is git-ignored): they are biometric data.

## Configuration

- Recognition thresholds and PAD settings live in `config.py` (`Settings`). Existing recognition defaults (similarity 0.45,
  margin 0.05, min votes 3, ...) are unchanged by the anti-spoofing upgrade.
- Environment variables: see `.env.example` (`ALLOWED_ORIGINS`, `COOKIE_SECURE`, `WORKER_PORT`, `PAD_PROVIDER`,
  `ENROLL_REQUIRE_LIVENESS`).
- Cameras are managed on the **Cameras** page and stored server-side in `data/cameras.json`. RTSP URLs and passwords are
  never sent to the browser; the API returns a masked form.

## Tests

```bash
python -m pytest tests -q -rs          # backend + PAD + golden regression
cd frontend && npm run typecheck && npm test
```

The PAD gating tests use a simulated provider to prove the gating logic (they do not measure model accuracy). The golden
test proves that with `liveness_mode="off"` the pipeline behaves exactly as it did before the anti-spoofing upgrade.

## Resetting data

Stop the worker and API, back up `data/attendance_system.db`, then delete rows with `sqlite3` or remove the file to start
completely fresh (the first-run setup then appears again). Restart the worker afterwards.

## Privacy and security

- Embeddings and templates are never sent to the browser or over WebSockets, and are never logged.
- Snapshots are off by default (`save_snapshots=False`).
- Use HTTPS and `COOKIE_SECURE=1` for anything beyond a trusted local network.
- Whether and how you may process faces (for example under India's DPDP Act, GDPR, or school/institution policy) needs
  review by your institution. This project does not claim legal compliance.

## Limitations

- A single-frame PAD model can be fooled by high-quality 3D masks, replays tuned against the model, or injection
  attacks on the camera feed. Treat it as one layer, not proof.
- Models were trained on phone-style portrait frames; a wide gate camera may behave differently. Calibrate on your own data.
- Tracks that are already identified and LIVE are re-checked only at the re-verify interval.
- Face-recognition accuracy depends on camera placement, lighting and enrollment quality.

## Model licenses

- **Face detection/recognition:** InsightFace `buffalo_l`. Check the InsightFace model license for your intended use; it is
  not a blanket commercial license.
- **Anti-spoofing:** MiniFASNet from [minivision-ai/Silent-Face-Anti-Spoofing](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing),
  Apache License 2.0 (verify the `LICENSE` in that repository for the version you use).

## Docs

- [`docs/RUNNING.md`](docs/RUNNING.md): start-up details
- [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md): REST and WebSocket contract
- [`docs/UPGRADE_STATUS.md`](docs/UPGRADE_STATUS.md): what was verified and what was not
- [`docs/PHASE1_AUDIT.md`](docs/PHASE1_AUDIT.md): audit of the original code
