"""
backend/app.py - FastAPI application.

    PYTHONPATH=. uvicorn backend.app:app --host 127.0.0.1 --port 8000      (see docs/RUNNING.md)

Imports the existing flat modules (database.py, config.py, pad_store.py ...). Never imports auth.py,
ui_common.py, dashboard.py or pages/ (they import Streamlit). Roles are enforced HERE on every route and
WebSocket; the React UI only hides things. Contract: docs/API_CONTRACT.md.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import logging
import os
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import (Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

import pad_store
from backend import services as V
from backend.security import AuthError, AuthService
from backend.worker_client import WorkerClient, WorkerError, WorkerUnavailable
from config import ANTISPOOFING_MODEL_DIR, DATA_DIR, DB_PATH, DEFAULT_SETTINGS
from database import Store

log = logging.getLogger("api")
COOKIE = "fa_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
MAX_UPLOAD = 8 * 1024 * 1024
MAX_VIDEO = 500 * 1024 * 1024
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ----------------------------------------------------------------------------- schemas
class Creds(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetupBody(Creds):
    setup_token: str


class ChangePw(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


class StudentProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = ""
    phone: str = ""
    department: str = ""
    batch: str = ""
    expected_time: str = ""


class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: str
    password: str = Field(min_length=10, max_length=256)
    roll_number: Optional[str] = None


class UserPatch(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None
    roll_number: Optional[str] = None


class StudentAccounts(BaseModel):
    roll_numbers: List[str] = Field(max_length=2000)


class CameraBody(BaseModel):
    name: str
    type: str
    source: Optional[str] = None
    description: str = ""
    enabled: bool = True


class LiveStart(BaseModel):
    source: str
    camera_id: Optional[str] = None
    webcam_index: int = 0
    file_path: Optional[str] = None
    loop: bool = False
    camera_label: Optional[str] = None
    settings: Optional[dict] = None


class EnrollSession(StudentProfile):
    roll_number: str = Field(min_length=1, max_length=40)
    mode: str = "replace"


# ----------------------------------------------------------------------------- factory
def create_app(*, auth: Optional[AuthService] = None, store: Optional[Store] = None,
               worker: Optional[WorkerClient] = None, cameras: Optional[V.CameraRepo] = None,
               allowed_origins: Optional[List[str]] = None, cookie_secure: Optional[bool] = None,
               start_background: bool = True) -> FastAPI:
    origins = allowed_origins or [o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
    secure = cookie_secure if cookie_secure is not None else os.environ.get("COOKIE_SECURE", "0") == "1"
    history: dict = {"cpu": deque(maxlen=720), "ram": deque(maxlen=720), "fps": deque(maxlen=720)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = app.state
        s.store = store or Store(DB_PATH)
        with s.store._conn() as c:
            have = {r[1] for r in c.execute("PRAGMA table_info(attendance_logs)")}
        if "pad_state" not in have:
            pad_store.migrate_pad_schema(s.store.path)               # additive, backs up first
        s.auth = auth or AuthService(s.store.path, setup_token=os.environ.get("SETUP_TOKEN"))
        s.worker = worker or WorkerClient()
        s.cameras = cameras or V.CameraRepo(os.path.join(DATA_DIR, "cameras.json"))
        if s.auth.setup_required():
            log.warning("FIRST-RUN SETUP REQUIRED. One-time setup token: %s", s.auth.setup_token)
            print(f"\n*** FIRST-RUN SETUP: open the web app /login and enter this one-time token: {s.auth.setup_token}\n", flush=True)
        task = asyncio.create_task(_sample_metrics(s)) if start_background else None
        yield
        if task:
            task.cancel()

    async def _sample_metrics(s):
        while True:
            m = V.system_metrics()
            now = time.time()
            for k, v in (("cpu", m["cpu_percent"]), ("ram", m["ram_percent"]), ("fps", (s.worker.status or {}).get("fps"))):
                if v is not None:
                    history[k].append([now, v])
            await asyncio.sleep(5)

    app = FastAPI(title="Face attendance API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json" if os.environ.get("API_DOCS") == "1" else None)
    # ---- error mapping
    @app.exception_handler(AuthError)
    async def _auth_err(_: Request, exc: AuthError):
        headers = {"Retry-After": str(exc.retry_after)} if hasattr(exc, "retry_after") else None
        return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers=headers)

    @app.exception_handler(WorkerUnavailable)
    async def _wu(_: Request, exc: WorkerUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(WorkerError)
    async def _we(_: Request, exc: WorkerError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.code)

    # ---- auth dependencies
    def _origin_ok(origin: Optional[str], host: Optional[str]) -> bool:
        if not origin:
            return True                                              # non-browser clients cannot be CSRF'd
        return origin in origins or (host is not None and origin.split("://", 1)[-1] == host)

    def session_of(request: Request) -> dict:
        sess = request.app.state.auth.resolve(request.cookies.get(COOKIE))
        if not sess:
            raise HTTPException(401, "Not signed in.")
        if request.method in UNSAFE:
            if not _origin_ok(request.headers.get("origin"), request.headers.get("host")):
                raise HTTPException(403, "Bad origin.")
            if not AuthService.csrf_ok(sess, request.headers.get("x-csrf-token")):
                raise HTTPException(403, "Missing or invalid CSRF token.")
        return sess

    def require(*roles: str, allow_reset: bool = False):
        def dep(sess: dict = Depends(session_of)) -> dict:
            if sess["must_reset"] and not allow_reset:
                raise HTTPException(403, "Password change required.")
            if sess["user"]["role"] not in roles:
                raise HTTPException(403, "Not allowed for your role.")
            return sess
        return dep

    ADMIN, STAFF, STUDENT = require("admin"), require("admin", "operator"), require("student")
    ANY = require("admin", "operator", "student", allow_reset=True)

    def ip(request: Request) -> str:
        return request.client.host if request.client else ""

    def audit(request: Request, user: str, action: str, details: str = "") -> None:
        request.app.state.store.log_audit(user, action, details, ip(request))

    def set_cookie(resp: Response, token: str, ttl: float) -> None:
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=secure, max_age=int(ttl * 3600), path="/")

    # ------------------------------------------------------------------ auth routes
    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        return {"setup_required": request.app.state.auth.setup_required()}

    @app.post("/api/auth/setup")
    async def auth_setup(body: SetupBody, request: Request, response: Response):
        a = request.app.state.auth
        if not _origin_ok(request.headers.get("origin"), request.headers.get("host")):
            raise HTTPException(403, "Bad origin.")
        a.setup(body.setup_token, body.username, body.password, ip(request))
        audit(request, body.username, "setup_admin", "first-run admin created")
        s = a.login(body.username, body.password, ip(request))
        set_cookie(response, s["token"], a.ttl.total_seconds() / 3600)
        return {"user": s["user"], "csrf_token": s["csrf"], "must_reset_password": False}

    @app.post("/api/auth/login")
    async def login(body: Creds, request: Request, response: Response):
        a = request.app.state.auth
        if not _origin_ok(request.headers.get("origin"), request.headers.get("host")):
            raise HTTPException(403, "Bad origin.")
        try:
            s = a.login(body.username, body.password, ip(request))
        except AuthError as exc:
            audit(request, body.username[:64], "login_failed", str(exc))
            raise
        audit(request, s["user"]["username"], "login", "")
        set_cookie(response, s["token"], a.ttl.total_seconds() / 3600)
        return {"user": s["user"], "csrf_token": s["csrf"], "must_reset_password": s["must_reset"]}

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response, sess=Depends(session_of)):
        request.app.state.auth.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        audit(request, sess["user"]["username"], "logout")
        return {"ok": True}

    @app.get("/api/auth/me")
    async def me(sess=Depends(session_of)):
        return {"user": sess["user"], "csrf_token": sess["csrf"], "must_reset_password": sess["must_reset"]}

    @app.post("/api/auth/change-password")
    async def change_pw(body: ChangePw, request: Request, sess=Depends(ANY)):
        request.app.state.auth.change_password(sess["user"]["username"], body.current_password, body.new_password)
        audit(request, sess["user"]["username"], "password_changed")
        return {"ok": True}

    # ------------------------------------------------------------------ dashboard / attendance / analytics
    @app.get("/api/dashboard")
    async def dashboard(request: Request, _=Depends(STAFF)):
        return await asyncio.to_thread(V.dashboard, request.app.state.store)

    def att_filters(start_date: Optional[str] = None, end_date: Optional[str] = None, roll_number: Optional[str] = None,
                    name: Optional[str] = None, camera_label: Optional[str] = None, direction: Optional[str] = None) -> dict:
        for d in (start_date, end_date):
            if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                raise HTTPException(422, "Dates must be YYYY-MM-DD.")
        return {k: v for k, v in dict(start_date=start_date, end_date=end_date, roll_number=roll_number, name=name,
                                      camera_label=camera_label, direction=direction).items() if v}

    @app.get("/api/attendance")
    async def attendance(request: Request, page: int = 1, page_size: int = 25, f: dict = Depends(att_filters), _=Depends(STAFF)):
        return await asyncio.to_thread(V.list_attendance, request.app.state.store, f, page, page_size)

    @app.get("/api/attendance/export.csv")
    async def attendance_export(request: Request, f: dict = Depends(att_filters), sess=Depends(STAFF)):
        text = await asyncio.to_thread(V.attendance_csv, request.app.state.store, f)
        audit(request, sess["user"]["username"], "export_attendance_csv", str(f))
        return PlainTextResponse(text, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendance.csv"})

    @app.get("/api/attendance/cameras")
    async def att_cameras(request: Request, _=Depends(STAFF)):
        return V.attendance_cameras(request.app.state.store)

    @app.get("/api/analytics")
    async def analytics(request: Request, days: int = 30, _=Depends(STAFF)):
        return await asyncio.to_thread(V.analytics, request.app.state.store, days)

    # ------------------------------------------------------------------ students
    @app.get("/api/students")
    async def students(request: Request, page: int = 1, page_size: int = 25, q: str = "", _=Depends(STAFF)):
        return V.list_students(request.app.state.store, q, page, page_size)

    @app.get("/api/students/{roll}")
    async def student(roll: str, request: Request, _=Depends(STAFF)):
        return V.get_student(request.app.state.store, roll)

    @app.post("/api/students/{roll}/profile")
    async def student_update(roll: str, body: StudentProfile, request: Request, sess=Depends(ADMIN)):
        out = V.update_student(request.app.state.store, roll, body.model_dump())
        audit(request, sess["user"]["username"], "student_updated", roll)
        return out

    @app.delete("/api/students/{roll}")
    async def student_delete(roll: str, request: Request, sess=Depends(ADMIN)):
        V.delete_student(request.app.state.store, roll)
        audit(request, sess["user"]["username"], "student_deleted", roll)
        return {"ok": True}

    @app.post("/api/students/import")
    async def students_import(request: Request, file: UploadFile = File(...), sess=Depends(ADMIN)):
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "File too large.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "CSV must be UTF-8.")
        out = V.import_students_csv(request.app.state.store, text)
        audit(request, sess["user"]["username"], "students_imported", f"updated={out['updated']} skipped={out['skipped']}")
        return out

    # ------------------------------------------------------------------ enrollment (runs in the worker)
    async def rpc(request: Request, name: str, *args, timeout: float = 30.0):
        return await asyncio.to_thread(request.app.state.worker.rpc, name, *args, timeout=timeout)

    @app.get("/api/enrollment/status")
    async def enroll_status(request: Request, _=Depends(ADMIN)):
        return await rpc(request, "enroll_status")

    @app.post("/api/enrollment/session")
    async def enroll_open(body: EnrollSession, request: Request, _=Depends(ADMIN)):
        return await rpc(request, "enroll_open", body.model_dump())

    @app.post("/api/enrollment/session/{sid}/sample")
    async def enroll_sample(sid: str, request: Request, image: UploadFile = File(...), _=Depends(ADMIN)):
        raw = await image.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "Image too large.")
        st = await rpc(request, "enroll_status")
        if st["require_liveness"] and st["pad"]["state"] != "READY":
            raise HTTPException(503, "Anti-spoofing is not configured; camera enrollment is disabled by ENROLL_REQUIRE_LIVENESS.")
        return await rpc(request, "enroll_sample", sid, raw)

    @app.post("/api/enrollment/session/{sid}/finish")
    async def enroll_finish(sid: str, request: Request, sess=Depends(ADMIN)):
        out = await rpc(request, "enroll_finish", sid)
        audit(request, sess["user"]["username"], "student_enrolled_camera",
              f"templates={out['templates']} liveness_verified={out['liveness_verified']}")
        return out

    @app.delete("/api/enrollment/session/{sid}")
    async def enroll_cancel(sid: str, request: Request, _=Depends(ADMIN)):
        return await rpc(request, "enroll_cancel", sid)

    @app.post("/api/enrollment/photos")
    async def enroll_photos(request: Request, roll_number: str = Form(...), name: str = Form(...), mode: str = Form("replace"),
                            files: List[UploadFile] = File(...), sess=Depends(ADMIN)):
        if mode not in ("replace", "append"):
            raise HTTPException(422, "mode must be replace or append")
        blobs = []
        for f in files[:8]:
            b = await f.read(MAX_UPLOAD + 1)
            if len(b) > MAX_UPLOAD:
                raise HTTPException(413, f"{f.filename} too large.")
            blobs.append(b)
        out = await rpc(request, "enroll_photos", {"roll_number": roll_number, "name": name, "mode": mode,
                                                   "filenames": [f.filename for f in files[:8]]}, blobs)
        audit(request, sess["user"]["username"], "student_enrolled_photos",
              f"{roll_number.upper()} templates={out['templates']} - liveness NOT verified (uploaded photos)")
        return out

    # ------------------------------------------------------------------ users
    def user_out(r) -> dict:
        return {"username": r["username"], "role": r["role"], "roll_number": r["roll_number"], "must_reset": bool(r["must_reset"]),
                "has_password": r["password_hash"] is not None, "created_at": r["created_at"], "disabled": bool(r["disabled"])}

    @app.get("/api/users")
    async def users(request: Request, _=Depends(ADMIN)):
        return [user_out(r) for r in request.app.state.auth.list_users()]

    @app.post("/api/users")
    async def users_create(body: NewUser, request: Request, sess=Depends(ADMIN)):
        r = request.app.state.auth.create_user(body.username, body.role, body.password, body.roll_number)
        audit(request, sess["user"]["username"], "user_created", f"{body.username} role={body.role}")
        return user_out(r)

    @app.post("/api/users/student-accounts")
    async def users_students(body: StudentAccounts, request: Request, sess=Depends(ADMIN)):
        a, st, created = request.app.state.auth, request.app.state.store, []
        for roll in dict.fromkeys(x.strip().upper() for x in body.roll_numbers if x.strip()):
            with st._conn() as c:
                if not c.execute("SELECT 1 FROM students WHERE roll_number=?", (roll,)).fetchone():
                    continue
            if a.get_user(roll):
                continue
            tmp = secrets.token_urlsafe(12)
            a.create_user(roll, "student", tmp, roll, must_reset=True)
            created.append({"username": roll, "temporary_password": tmp})
        audit(request, sess["user"]["username"], "student_accounts_created", f"count={len(created)}")
        return {"created": created}

    @app.patch("/api/users/{username}")
    async def users_patch(username: str, body: UserPatch, request: Request, sess=Depends(ADMIN)):
        r = request.app.state.auth.update_user(username, role=body.role, disabled=body.disabled,
                                               roll_number=body.roll_number, acting=sess["user"]["username"])
        audit(request, sess["user"]["username"], "user_updated", f"{username} {body.model_dump(exclude_none=True)}")
        return user_out(r)

    @app.post("/api/users/{username}/temporary-password")
    async def users_tmp(username: str, request: Request, sess=Depends(ADMIN)):
        tmp = request.app.state.auth.temporary_password(username)
        audit(request, sess["user"]["username"], "user_password_reset", username)
        return {"temporary_password": tmp}

    @app.delete("/api/users/{username}")
    async def users_delete(username: str, request: Request, sess=Depends(ADMIN)):
        request.app.state.auth.delete_user(username, acting=sess["user"]["username"])
        audit(request, sess["user"]["username"], "user_deleted", username)
        return {"ok": True}

    # ------------------------------------------------------------------ cameras
    def cam_list(request: Request) -> list:
        st = request.app.state.worker.status or {}
        live = st.get("camera_label") if st.get("running") else None
        return request.app.state.cameras.list(live, st.get("error"))

    @app.get("/api/cameras")
    async def cameras_list(request: Request, _=Depends(STAFF)):
        return cam_list(request)

    @app.post("/api/cameras")
    async def cameras_add(body: CameraBody, request: Request, sess=Depends(ADMIN)):
        out = request.app.state.cameras.upsert(None, body.name, body.type, body.source, body.description, body.enabled)
        audit(request, sess["user"]["username"], "camera_added", body.name)
        return out

    @app.put("/api/cameras/{cam_id}")
    async def cameras_put(cam_id: str, body: CameraBody, request: Request, sess=Depends(ADMIN)):
        out = request.app.state.cameras.upsert(cam_id, body.name, body.type, body.source, body.description, body.enabled)
        audit(request, sess["user"]["username"], "camera_changed", cam_id)
        return out

    @app.delete("/api/cameras/{cam_id}")
    async def cameras_del(cam_id: str, request: Request, sess=Depends(ADMIN)):
        request.app.state.cameras.delete(cam_id)
        audit(request, sess["user"]["username"], "camera_deleted", cam_id)
        return {"ok": True}

    # ------------------------------------------------------------------ live worker control
    async def worker_status(request: Request) -> dict:
        w = request.app.state.worker
        try:
            await asyncio.to_thread(w.refresh_status)
            await asyncio.sleep(0.15)
        except WorkerUnavailable:
            return offline_status()
        return dict(w.status, viewers=w.viewers)

    def offline_status() -> dict:
        from backend.worker import TUNABLE
        import antispoof
        return {"running": False, "source_label": "", "camera_label": "", "fps": 0, "proc_ms": 0, "det_ms": 0, "rec_ms": 0,
                "pad_ms": 0, "faces": 0, "session_logged": 0, "provider": "", "liveness_mode": DEFAULT_SETTINGS.liveness_mode,
                "pad": antispoof.MiniFASNetPAD().health(),
                "settings": {k: getattr(DEFAULT_SETTINGS, k) for k in TUNABLE},
                "error": "Gate worker is not running. Start it with: python -m backend.worker", "viewers": 0}

    @app.get("/api/live/status")
    async def live_status(request: Request, _=Depends(STAFF)):
        return await worker_status(request)

    @app.post("/api/live/start")
    async def live_start(body: LiveStart, request: Request, sess=Depends(ADMIN)):
        if body.source not in ("server_webcam", "camera", "file", "browser"):
            raise HTTPException(422, "Unknown source.")
        if body.source == "camera":
            if not body.camera_id:
                raise HTTPException(422, "camera_id required.")
            request.app.state.cameras.get_source(body.camera_id)           # 404 if unknown
        if body.source == "file":
            base = os.path.realpath(os.path.join(DATA_DIR, "uploads"))
            if not body.file_path or not os.path.realpath(body.file_path).startswith(base + os.sep):
                raise HTTPException(422, "file_path must be a file uploaded through /live/upload-video.")
        request.app.state.worker.send(("start", body.model_dump(exclude_none=True)))
        audit(request, sess["user"]["username"], "live_started", f"source={body.source} camera={body.camera_id or body.camera_label or ''}")
        await asyncio.sleep(0.5)
        return await worker_status(request)

    @app.post("/api/live/stop")
    async def live_stop(request: Request, sess=Depends(ADMIN)):
        request.app.state.worker.send(("stop",))
        audit(request, sess["user"]["username"], "live_stopped")
        await asyncio.sleep(0.3)
        return await worker_status(request)

    @app.put("/api/live/settings")
    async def live_settings(request: Request, patch: dict, sess=Depends(ADMIN)):
        from backend.worker import apply_tuning
        try:
            apply_tuning(DEFAULT_SETTINGS, patch)                              # validate before sending
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        request.app.state.worker.send(("settings", patch))
        audit(request, sess["user"]["username"], "live_settings_changed", str(patch))
        await asyncio.sleep(0.5)
        return await worker_status(request)

    @app.post("/api/live/upload-video")
    async def live_upload(request: Request, file: UploadFile = File(...), sess=Depends(ADMIN)):
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in VIDEO_EXT:
            raise HTTPException(422, "Unsupported video type.")
        folder = os.path.join(DATA_DIR, "uploads")
        os.makedirs(folder, exist_ok=True)
        path, size = os.path.join(folder, secrets.token_hex(12) + ext), 0
        with open(path, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_VIDEO:
                    out.close(); os.remove(path)
                    raise HTTPException(413, "Video too large.")
                out.write(chunk)
        audit(request, sess["user"]["username"], "video_uploaded", f"{size} bytes")
        return {"file_path": path}

    @app.get("/api/live/events")
    async def live_events(request: Request, limit: int = 50, _=Depends(STAFF)):
        w = request.app.state.worker
        w.available()
        return [e for _, e in list(w.events)[-min(200, limit):]][::-1]

    # ------------------------------------------------------------------ system / inspector / security / audit
    @app.get("/api/system")
    async def system(request: Request, _=Depends(STAFF)):
        st = await worker_status(request)
        m = V.system_metrics()
        alerts = []
        if not st["running"]:
            alerts.append({"level": "warning", "message": st.get("error") or "Gate worker is idle."})
        if st["liveness_mode"] == "off":
            alerts.append({"level": "warning", "message": "Anti-spoofing is OFF: photos and phone screens are not detected."})
        if st["pad"]["state"] != "READY":
            alerts.append({"level": "error" if st["pad"]["state"] == "ERROR" else "warning",
                           "message": f"PAD {st['pad']['state']}: {st['pad']['reason']}"})
        if m["cpu_percent"] is not None and m["cpu_percent"] > 90:
            alerts.append({"level": "warning", "message": f"CPU at {m['cpu_percent']:.0f}%"})
        size = os.path.getsize(request.app.state.store.path) / 1e6 if os.path.exists(request.app.state.store.path) else 0
        return {**m, "provider": st["provider"], "fps": st["fps"], "proc_ms": st["proc_ms"], "det_ms": st["det_ms"],
                "rec_ms": st["rec_ms"], "pad_ms": st["pad_ms"], "liveness_mode": st["liveness_mode"], "pad": st["pad"],
                "worker_running": st["running"], "db_size_mb": round(size, 2), "alerts": alerts,
                "history": {k: list(v) for k, v in history.items()}}

    @app.get("/api/inspector")
    async def inspector(request: Request, _=Depends(ADMIN)):
        st = await worker_status(request)
        out = await asyncio.to_thread(V.inspector, request.app.state.store, DEFAULT_SETTINGS, st["pad"], ANTISPOOFING_MODEL_DIR)
        out["settings"].update(st.get("settings", {}))
        return out

    @app.get("/api/security/alerts")
    async def security(request: Request, limit: int = 50, _=Depends(STAFF)):
        return V.security_alerts(request.app.state.store, limit)

    @app.get("/api/audit")
    async def audit_list(request: Request, page: int = 1, page_size: int = 25, _=Depends(ADMIN)):
        return V.audit_page(request.app.state.store, page, page_size)

    # ------------------------------------------------------------------ student self-service
    def roll_of(sess: dict) -> str:
        roll = sess["user"]["roll_number"]
        if not roll:
            raise HTTPException(404, "This account is not linked to a student record.")
        return roll

    @app.get("/api/me/profile")
    async def me_profile(request: Request, sess=Depends(STUDENT)):
        return V.get_student(request.app.state.store, roll_of(sess))

    @app.get("/api/me/attendance")
    async def me_attendance(request: Request, page: int = 1, page_size: int = 25, start_date: Optional[str] = None,
                            end_date: Optional[str] = None, sess=Depends(STUDENT)):
        f = att_filters(start_date, end_date)
        f["exact_roll"] = roll_of(sess)                                    # scoped server-side, never from the query
        return V.list_attendance(request.app.state.store, f, page, page_size)

    @app.get("/api/me/summary")
    async def me_summary(request: Request, sess=Depends(STUDENT)):
        return V.my_summary(request.app.state.store, roll_of(sess))

    # ------------------------------------------------------------------ websockets
    async def ws_auth(ws: WebSocket, roles=("admin", "operator")) -> Optional[dict]:
        origin, host = ws.headers.get("origin"), ws.headers.get("host")
        if not _origin_ok(origin, host) or origin is None:
            await ws.close(code=4403)
            return None
        sess = ws.app.state.auth.resolve(ws.cookies.get(COOKIE))
        if not sess:
            await ws.close(code=4401)
            return None
        if sess["must_reset"] or sess["user"]["role"] not in roles:
            await ws.close(code=4403)
            return None
        await ws.accept()
        return sess

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket):
        if not await ws_auth(ws):
            return
        w = ws.app.state.worker
        last = w.event_seq
        try:
            tick = 0
            while True:
                if w.available():
                    for seq, ev in list(w.events):
                        if seq > last:
                            last = seq
                            await ws.send_json({"kind": "event", "event": ev})
                    if tick % 12 == 0:
                        await asyncio.to_thread(w.refresh_status)
                        await ws.send_json({"kind": "status", "status": dict(w.status, viewers=w.viewers)})
                else:
                    if tick % 12 == 0:
                        await ws.send_json({"kind": "status", "status": offline_status()})
                tick += 1
                await asyncio.sleep(0.083)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.websocket("/ws/preview")
    async def ws_preview(ws: WebSocket):
        if not await ws_auth(ws):
            return
        w = ws.app.state.worker
        counted = False
        try:
            w.viewer(+1); counted = True
            seq = w.frame_seq
            while True:
                if w.frame is not None and w.frame_seq != seq:
                    seq, f = w.frame_seq, w.frame
                    await ws.send_json({"kind": "frame", "jpeg_b64": base64.b64encode(f["jpeg"]).decode(), "width": f["width"],
                                        "height": f["height"], "tracks": f["tracks"], "fps": f["fps"], "proc_ms": f["proc_ms"]})
                await asyncio.sleep(0.04)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if counted:
                w.viewer(-1)

    @app.websocket("/ws/browser-camera")
    async def ws_browser(ws: WebSocket):
        sess = await ws_auth(ws, roles=("admin", "operator"))
        if not sess:
            return
        w = ws.app.state.worker
        await asyncio.to_thread(w.refresh_status)
        await asyncio.sleep(0.15)
        if not (w.status.get("running") and w.status.get("source_label") == "browser camera"):
            await ws.close(code=4409)
            return
        n = 0
        try:
            while True:
                data = await ws.receive_bytes()
                if len(data) > 1_500_000:
                    continue
                w.send(("frame", data))
                n += 1
                if n % 30 == 0:
                    await ws.send_json({"kind": "ack", "dropped": w.status.get("browser_dropped", 0)})
        except (WebSocketDisconnect, RuntimeError, WorkerUnavailable):
            return

    return app


class _LazyApp:
    """`uvicorn backend.app:app` - the real app is created on first ASGI call."""
    _app = None

    async def __call__(self, scope, receive, send):
        if _LazyApp._app is None:
            _LazyApp._app = create_app()
        await _LazyApp._app(scope, receive, send)


app = _LazyApp()
