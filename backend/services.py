"""
backend/services.py - framework-free data services over the existing `Store` (sqlite3).
Nothing here returns embeddings or camera credentials. Imported by the FastAPI routers and unit-tested
without FastAPI.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from backend.security import BadRequest, Conflict, NotFound, mask_source
from database import Store

ATT_COLS = ("id", "roll_number", "name", "timestamp", "direction", "similarity", "source", "camera_label")
STUDENT_COLS = "s.roll_number, s.name, s.email, s.phone, s.department, s.batch, s.expected_time, s.created_at"


def _page(page: int, size: int):
    page, size = max(1, int(page)), min(200, max(1, int(size)))
    return page, size, (page - 1) * size


def _has_col(c, table: str, col: str) -> bool:
    return any(r[1] == col for r in c.execute(f"PRAGMA table_info({table})"))


# ----------------------------------------------------------------------------- attendance
def _att_where(f: dict):
    q, p = " WHERE 1=1", []
    if f.get("start_date"):
        q += " AND timestamp >= ?"; p.append(f["start_date"])
    if f.get("end_date"):
        q += " AND timestamp <= ?"; p.append(f["end_date"] + " 23:59:59")
    if f.get("roll_number"):
        q += " AND roll_number LIKE ?"; p.append(f"%{f['roll_number']}%")
    if f.get("name"):
        q += " AND name LIKE ?"; p.append(f"%{f['name']}%")
    if f.get("camera_label"):
        q += " AND camera_label = ?"; p.append(f["camera_label"])
    if f.get("direction"):
        q += " AND direction = ?"; p.append(f["direction"])
    if f.get("exact_roll"):
        q += " AND roll_number = ?"; p.append(f["exact_roll"])
    return q, p


def _att_select(c) -> str:
    cols = list(ATT_COLS) + [x if _has_col(c, "attendance_logs", x) else f"NULL AS {x}" for x in ("pad_state", "pad_score")]
    return ", ".join(cols)


def list_attendance(store: Store, filters: dict, page: int = 1, page_size: int = 25) -> dict:
    page, size, off = _page(page, page_size)
    where, params = _att_where(filters)
    with store._conn() as c:
        total = c.execute("SELECT COUNT(*) FROM attendance_logs" + where, params).fetchone()[0]
        rows = c.execute(f"SELECT {_att_select(c)} FROM attendance_logs{where} ORDER BY timestamp DESC, id DESC "
                         "LIMIT ? OFFSET ?", params + [size, off]).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": size}


def attendance_csv(store: Store, filters: dict, limit: int = 100000) -> str:
    where, params = _att_where(filters)
    with store._conn() as c:
        rows = c.execute(f"SELECT {_att_select(c)} FROM attendance_logs{where} ORDER BY timestamp DESC LIMIT ?",
                         params + [limit]).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([k for k in rows[0].keys()] if rows else list(ATT_COLS) + ["pad_state", "pad_score"])
    for r in rows:
        w.writerow([("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for v in tuple(r)])  # CSV-injection guard
    return buf.getvalue()


def attendance_cameras(store: Store) -> List[str]:
    with store._conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT camera_label FROM attendance_logs WHERE camera_label IS NOT NULL ORDER BY 1")]


# ----------------------------------------------------------------------------- dashboard / analytics
def dashboard(store: Store) -> dict:
    recent = list_attendance(store, {}, 1, 15)["items"]
    return {
        "today_unique": store.today_unique_count(), "today_scans": store.today_total_scans(),
        "today_known": store.today_known_count(), "today_unknown": store.today_unknown_count(),
        "enrolled_students": len(store.list_students()),
        "hourly": [{"hour": h, "count": n} for h, n in store.hourly_counts_today()],
        "trends": [{"date": d, "unique": u, "total": t} for d, u, t in store.get_attendance_trends(14)],
        "peak_hours": [{"hour": h, "count": n} for h, n in store.get_peak_hours(7)],
        "late_arrivals": store.get_late_arrivals(),
        "recent": recent,
    }


def analytics(store: Store, days: int = 30) -> dict:
    days = min(365, max(1, days))
    return {"trends": [{"date": d, "unique": u, "total": t} for d, u, t in store.get_attendance_trends(days)],
            "peak_hours": [{"hour": h, "count": n} for h, n in store.get_peak_hours(days)],
            "camera_stats": store.get_camera_stats(),
            "absent": [{"roll_number": a["roll_number"], "name": a["name"]} for a in store.get_absent_students(min(days, 30))],
            "late_arrivals": store.get_late_arrivals()}


# ----------------------------------------------------------------------------- students
def _student_row(c, roll: str) -> Optional[dict]:
    r = c.execute(f"SELECT {STUDENT_COLS}, (SELECT COUNT(*) FROM face_templates t WHERE t.student_id=s.id) AS template_count "
                  "FROM students s WHERE s.roll_number=?", (roll.strip().upper(),)).fetchone()
    return dict(r) if r else None


def list_students(store: Store, q: str = "", page: int = 1, page_size: int = 25) -> dict:
    page, size, off = _page(page, page_size)
    like = f"%{q.strip()}%"
    with store._conn() as c:
        total = c.execute("SELECT COUNT(*) FROM students WHERE roll_number LIKE ? OR name LIKE ?", (like, like)).fetchone()[0]
        rows = c.execute(f"SELECT {STUDENT_COLS}, (SELECT COUNT(*) FROM face_templates t WHERE t.student_id=s.id) AS template_count "
                         "FROM students s WHERE s.roll_number LIKE ? OR s.name LIKE ? ORDER BY s.roll_number LIMIT ? OFFSET ?",
                         (like, like, size, off)).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": size}


def get_student(store: Store, roll: str) -> dict:
    with store._conn() as c:
        s = _student_row(c, roll)
    if not s:
        raise NotFound("No such student.")
    s["attendance_percentage_30d"] = store.get_attendance_percentage(s["roll_number"], 30)
    return s


def update_student(store: Store, roll: str, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("Name is required.")
    with store._conn() as c:
        if not _student_row(c, roll):
            raise NotFound("No such student.")
        c.execute("UPDATE students SET name=?, email=?, phone=?, department=?, batch=?, expected_time=? WHERE roll_number=?",
                  (name, data.get("email", ""), data.get("phone", ""), data.get("department", ""), data.get("batch", ""),
                   data.get("expected_time", ""), roll.strip().upper()))
    return get_student(store, roll)


def delete_student(store: Store, roll: str) -> None:
    if not store.delete_student(roll.strip().upper()):
        raise NotFound("No such student.")


def import_students_csv(store: Store, text: str) -> dict:
    """Metadata import for EXISTING students (Store.bulk_import_students cannot create students without a face)."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "roll_number" not in [f.strip() for f in reader.fieldnames] or "name" not in [f.strip() for f in reader.fieldnames]:
        raise BadRequest("CSV needs at least the columns roll_number and name.")
    rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader][:5000]
    ok, bad, msgs = store.bulk_import_students(rows)
    return {"updated": ok, "skipped": bad, "errors": msgs[:100]}


# ----------------------------------------------------------------------------- student self-service
def my_summary(store: Store, roll: str) -> dict:
    now = datetime.now()
    day, week, month = (now.strftime("%Y-%m-%d"), (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
                        (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"))
    with store._conn() as c:
        sel = _att_select(c)
        today = [dict(r) for r in c.execute(f"SELECT {sel} FROM attendance_logs WHERE roll_number=? AND timestamp LIKE ? "
                                            "ORDER BY timestamp DESC", (roll, day + "%"))]
        wk = c.execute("SELECT COUNT(DISTINCT DATE(timestamp)) FROM attendance_logs WHERE roll_number=? AND timestamp>=?", (roll, week)).fetchone()[0]
        mo = c.execute("SELECT COUNT(DISTINCT DATE(timestamp)) FROM attendance_logs WHERE roll_number=? AND timestamp>=?", (roll, month)).fetchone()[0]
        tr = c.execute("SELECT DATE(timestamp) d, COUNT(*) n FROM attendance_logs WHERE roll_number=? AND timestamp>=? "
                       "GROUP BY d ORDER BY d", (roll, month)).fetchall()
    return {"today": today, "week_count": wk, "month_count": mo,
            "attendance_percentage_30d": store.get_attendance_percentage(roll, 30),
            "trends": [{"date": r["d"], "count": r["n"]} for r in tr]}


# ----------------------------------------------------------------------------- cameras (data/cameras.json stays server side)
CAM_TYPES = {"rtsp": "RTSP Stream", "webcam": "Webcam", "file": "Video File", "http": "HTTP Stream"}
_REV = {v: k for k, v in CAM_TYPES.items()}


class CameraRepo:
    def __init__(self, path: str):
        self.path, self._lock = path, threading.Lock()

    def _load(self) -> dict:
        try:
            return json.load(open(self.path))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        tmp = self.path + ".tmp"
        json.dump(data, open(tmp, "w"), indent=2)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _out(name: str, d: dict, status: str = "idle", err: Optional[str] = None) -> dict:
        t = _REV.get(d.get("type", ""), "rtsp")
        return {"id": name, "name": name, "type": t, "source_masked": mask_source(str(d.get("source", ""))),
                "description": d.get("description", ""), "enabled": bool(d.get("enabled", True)),
                "status": status, "last_error": err}

    def list(self, live_label: Optional[str] = None, error: Optional[str] = None) -> List[dict]:
        return [self._out(n, d, "live" if n == live_label and not error else "error" if n == live_label else "idle",
                          error if n == live_label else None) for n, d in sorted(self._load().items())]

    def get_source(self, cam_id: str) -> tuple:
        """(type, real source) for the worker. Never returned through the API."""
        d = self._load().get(cam_id)
        if not d:
            raise NotFound("No such camera.")
        return _REV.get(d.get("type", ""), "rtsp"), d.get("source", "")

    def upsert(self, cam_id: Optional[str], name: str, type_: str, source: Optional[str], description: str, enabled: bool) -> dict:
        name = name.strip()
        if not re.fullmatch(r"[\w .-]{1,60}", name):
            raise BadRequest("Camera name: 1-60 letters, digits, space, dot, dash or underscore.")
        if type_ not in CAM_TYPES:
            raise BadRequest("Invalid camera type.")
        with self._lock:
            data = self._load()
            if cam_id is None and name in data:
                raise Conflict("A camera with that name exists.")
            if cam_id is not None and cam_id not in data:
                raise NotFound("No such camera.")
            old = data.get(cam_id, {}) if cam_id else {}
            if source is None or source == "":
                if cam_id is None:
                    raise BadRequest("Source is required.")
                source = old.get("source", "")
            if cam_id and cam_id != name:
                data.pop(cam_id, None)
            data[name] = {"type": CAM_TYPES[type_], "source": source, "description": description, "enabled": enabled}
            self._save(data)
            return self._out(name, data[name])

    def delete(self, cam_id: str) -> None:
        with self._lock:
            data = self._load()
            if cam_id not in data:
                raise NotFound("No such camera.")
            del data[cam_id]
            self._save(data)


# ----------------------------------------------------------------------------- audit / security / inspector
def audit_page(store: Store, page: int = 1, page_size: int = 25) -> dict:
    page, size, off = _page(page, page_size)
    with store._conn() as c:
        total = c.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        rows = c.execute("SELECT id, timestamp, user, action, details, ip_address FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                         (size, off)).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": size}


def security_alerts(store: Store, limit: int = 50) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    with store._conn() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='pad_events'").fetchone():
            events, spoof = [], 0
        else:
            events = [dict(r) for r in c.execute("SELECT * FROM pad_events ORDER BY id DESC LIMIT ?", (min(200, limit),))]
            spoof = c.execute("SELECT COUNT(*) FROM pad_events WHERE state='SPOOF' AND timestamp LIKE ?", (today + "%",)).fetchone()[0]
    return {"pad_events": events, "unknown_today": store.today_unknown_count(), "spoof_today": spoof}


def inspector(store: Store, settings, pad_health: dict, model_dir: str) -> dict:
    import dataclasses
    gal = store.load_gallery()
    with store._conn() as c:
        templates = c.execute("SELECT COUNT(*) FROM face_templates").fetchone()[0]
    models = []
    for sub in ("buffalo_l",):
        models.append({"name": f"InsightFace {sub}", "present": os.path.isdir(os.path.expanduser(f"~/.insightface/models/{sub}"))})
    for e in (json.load(open(os.path.join(model_dir, "MODELS.json")))["models"] if os.path.exists(os.path.join(model_dir, "MODELS.json")) else []):
        models.append({"name": e["file"], "present": os.path.isfile(os.path.join(model_dir, e["file"]))})
    return {"settings": dataclasses.asdict(settings),
            "gallery": {"students": len(store.list_students()), "templates": templates, "version": store.gallery_version(),
                        "backend": getattr(gal, "backend", "faiss" if getattr(gal, "_index", None) is not None else "numpy")},
            "pad": pad_health, "models": models}


# ----------------------------------------------------------------------------- system metrics
def system_metrics() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {"cpu_percent": psutil.cpu_percent(interval=None), "ram_percent": vm.percent, "ram_used_mb": vm.used / 1e6}
    except ImportError:
        pass
    try:
        info = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        used = info["MemTotal"] - info["MemAvailable"]
        load = os.getloadavg()[0] / (os.cpu_count() or 1) * 100
        return {"cpu_percent": min(100.0, load), "ram_percent": used / info["MemTotal"] * 100, "ram_used_mb": used / 1024}
    except Exception:
        return {"cpu_percent": None, "ram_percent": None, "ram_used_mb": None}
