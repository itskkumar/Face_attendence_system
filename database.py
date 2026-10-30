"""
database.py - SQLite persistence + the in-memory face Gallery.

Design notes
  * WAL mode + one short-lived connection per operation -> safe for the CLI
    engine, several Streamlit sessions and WebRTC threads all hitting one file.
  * A student has MANY face templates (different poses / lighting) plus a
    centroid vector (the 'profile vector' stored on the student row).
  * log_attendance() does the cooldown check and the INSERT inside one
    BEGIN IMMEDIATE transaction, so two processes can never both log the same
    person inside the cooldown window.
  * Gallery matching is one NumPy matrix-vector product. At college scale
    (hundreds to a few thousand templates) that takes well under a millisecond,
    so an ANN index such as FAISS-HNSW would add complexity without benefit.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from config import DATE_FMT, DB_PATH
from vision_math import l2_normalize

EMB_DIM = 512
MAX_TEMPLATES_PER_STUDENT = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_number TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    embedding   BLOB NOT NULL,              -- centroid / profile vector (512 x float32)
    created_at  TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    department  TEXT,
    batch       TEXT,
    expected_time TEXT                      -- expected arrival time HH:MM
);
CREATE TABLE IF NOT EXISTS face_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    embedding  BLOB NOT NULL,
    quality    REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_templates_student ON face_templates(student_id);
CREATE TABLE IF NOT EXISTS attendance_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER REFERENCES students(id) ON DELETE SET NULL,
    roll_number TEXT NOT NULL,
    name        TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    direction   TEXT NOT NULL DEFAULT 'ENTRY',
    similarity  REAL,
    source      TEXT,
    camera_label TEXT DEFAULT 'default'    -- multi-camera support
);
CREATE INDEX IF NOT EXISTS idx_logs_ts   ON attendance_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_roll ON attendance_logs(roll_number, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_camera ON attendance_logs(camera_label);
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    user        TEXT NOT NULL,
    action      TEXT NOT NULL,
    details     TEXT,
    ip_address  TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(timestamp);
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer',  -- admin | viewer
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON system_health(timestamp);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> datetime:
    return datetime.now()


def _ts(dt: datetime) -> str:
    return dt.strftime(DATE_FMT)


def _blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _unblob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).copy()


@dataclass(frozen=True)
class StudentInfo:
    id: int
    roll_number: str
    name: str


@dataclass(frozen=True)
class GalleryMatch:
    student: StudentInfo
    similarity: float
    margin: float          # best similarity minus the best of any OTHER student


class Gallery:
    """Immutable snapshot of every enrolled template, ready for matrix matching."""

    def __init__(self, students: List[StudentInfo], matrix: np.ndarray,
                 owners: np.ndarray, version: int):
        self.students = students
        self.matrix = matrix            # (T, 512) float32, L2-normalised
        self.owners = owners            # (T,) index into `students`
        self.version = version

    @property
    def size(self) -> int:
        return len(self.students)

    def match(self, emb: np.ndarray) -> Optional[GalleryMatch]:
        if self.matrix.shape[0] == 0:
            return None
        q = l2_normalize(emb)
        sims = self.matrix @ q                                  # cosine similarities
        per_student = np.full(len(self.students), -1.0, dtype=np.float32)
        np.maximum.at(per_student, self.owners, sims)           # best template per student
        order = np.argsort(per_student)[::-1]
        best = float(per_student[order[0]])
        second = float(per_student[order[1]]) if len(order) > 1 else 0.0
        return GalleryMatch(self.students[int(order[0])], best, best - max(second, 0.0))

    @staticmethod
    def accept(m: Optional[GalleryMatch], threshold: float, margin: float) -> bool:
        return m is not None and m.similarity >= threshold and m.margin >= margin


class Store:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        init_db(path)

    # ------------------------------------------------------------ connections
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self, immediate: bool = False):
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    @staticmethod
    def _bump_version(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('gallery_version', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
        )

    # --------------------------------------------------------------- students
    def gallery_version(self) -> int:
        with self._conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key='gallery_version'").fetchone()
        return int(r["value"]) if r else 0

    def load_gallery(self) -> Gallery:
        with self._conn() as c:
            version_row = c.execute("SELECT value FROM meta WHERE key='gallery_version'").fetchone()
            srows = c.execute("SELECT id, roll_number, name, embedding FROM students ORDER BY id").fetchall()
            trows = c.execute("SELECT student_id, embedding FROM face_templates").fetchall()
        students = [StudentInfo(r["id"], r["roll_number"], r["name"]) for r in srows]
        index = {s.id: i for i, s in enumerate(students)}
        vecs, owners = [], []
        for r in srows:                                   # centroid is one more template
            vecs.append(_unblob(r["embedding"])); owners.append(index[r["id"]])
        for r in trows:
            if r["student_id"] in index:
                vecs.append(_unblob(r["embedding"])); owners.append(index[r["student_id"]])
        matrix = (l2_normalize(np.vstack(vecs)) if vecs
                  else np.zeros((0, EMB_DIM), dtype=np.float32))
        return Gallery(students, matrix.astype(np.float32),
                       np.asarray(owners, dtype=np.int64),
                       int(version_row["value"]) if version_row else 0)

    def add_student(self, roll_number: str, name: str, embeddings: Sequence[np.ndarray],
                    qualities: Optional[Sequence[float]] = None, mode: str = "replace",
                    email: str = "", phone: str = "", department: str = "",
                    batch: str = "", expected_time: str = "") -> Tuple[int, int]:
        """Enrol (or update) a student. mode='replace' swaps all templates, 'append' adds."""
        roll_number, name = roll_number.strip().upper(), name.strip()
        if not roll_number or not name:
            raise ValueError("name and roll number are required")
        embs = l2_normalize(np.vstack([np.asarray(e, dtype=np.float32) for e in embeddings]))
        if embs.shape[0] == 0:
            raise ValueError("at least one embedding is required")
        q = (np.asarray(qualities, dtype=np.float32) if qualities is not None
             else np.ones(embs.shape[0], dtype=np.float32))
        now = _ts(_now())
        with self._tx(immediate=True) as c:
            row = c.execute("SELECT id FROM students WHERE roll_number=?", (roll_number,)).fetchone()
            if row is None:
                sid = c.execute(
                    "INSERT INTO students(roll_number, name, embedding, created_at, email, phone, department, batch, expected_time) VALUES(?,?,?,?,?,?,?,?,?)",
                    (roll_number, name, _blob(embs[0]), now, email, phone, department, batch, expected_time)).lastrowid
            else:
                sid = row["id"]
                if mode == "replace":
                    c.execute("DELETE FROM face_templates WHERE student_id=?", (sid,))
            for e, qq in zip(embs, q):
                c.execute("INSERT INTO face_templates(student_id, embedding, quality, created_at) VALUES(?,?,?,?)",
                          (sid, _blob(e), float(qq), now))
            # keep only the newest N templates, then refresh the centroid
            c.execute("DELETE FROM face_templates WHERE student_id=? AND id NOT IN "
                      "(SELECT id FROM face_templates WHERE student_id=? ORDER BY id DESC LIMIT ?)",
                      (sid, sid, MAX_TEMPLATES_PER_STUDENT))
            rows = c.execute("SELECT embedding, quality FROM face_templates WHERE student_id=?", (sid,)).fetchall()
            mat = np.vstack([_unblob(r["embedding"]) for r in rows])
            w = np.maximum(np.array([r["quality"] for r in rows], dtype=np.float32), 1e-3)
            centroid = l2_normalize((mat * w[:, None]).sum(axis=0))
            c.execute("UPDATE students SET name=?, embedding=?, email=?, phone=?, department=?, batch=?, expected_time=? WHERE id=?",
                     (name, _blob(centroid), email, phone, department, batch, expected_time, sid))
            self._bump_version(c)
            n = len(rows)
        return int(sid), n

    def delete_student(self, roll_number: str) -> bool:
        with self._tx(immediate=True) as c:
            cur = c.execute("DELETE FROM students WHERE roll_number=?", (roll_number.strip().upper(),))
            self._bump_version(c)
        return cur.rowcount > 0

    def list_students(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT s.roll_number, s.name, s.created_at, COUNT(t.id) AS templates "
                "FROM students s LEFT JOIN face_templates t ON t.student_id = s.id "
                "GROUP BY s.id ORDER BY s.roll_number").fetchall()
        return [dict(r) for r in rows]

    def find_duplicate_identity(self, embeddings: Sequence[np.ndarray], roll_number: str,
                                threshold: float = 0.60) -> Optional[Tuple[str, str, float]]:
        """Is this face already enrolled under a DIFFERENT roll number?"""
        g = self.load_gallery()
        roll = roll_number.strip().upper()
        worst: Optional[Tuple[str, str, float]] = None
        for e in embeddings:
            m = g.match(e)
            if m and m.student.roll_number != roll and m.similarity >= threshold:
                if worst is None or m.similarity > worst[2]:
                    worst = (m.student.roll_number, m.student.name, m.similarity)
        return worst

    # ------------------------------------------------------------- attendance
    def log_attendance(self, roll_number: str, name: str, student_id: Optional[int],
                       similarity: float, direction: str, source: str,
                       cooldown_seconds: int, now: Optional[datetime] = None,
                       camera_label: str = "default") -> Tuple[bool, Optional[datetime]]:
        """
        Insert a log row unless this person was already logged within the cooldown.
        Returns (logged, last_logged_time). Atomic across threads and processes.
        """
        now = now or _now()
        with self._tx(immediate=True) as c:
            row = c.execute("SELECT MAX(timestamp) AS last FROM attendance_logs WHERE roll_number=?",
                            (roll_number,)).fetchone()
            last = datetime.strptime(row["last"], DATE_FMT) if row and row["last"] else None
            if last is not None and (now - last).total_seconds() < cooldown_seconds:
                return False, last
            c.execute(
                "INSERT INTO attendance_logs(student_id, roll_number, name, timestamp, direction, similarity, source, camera_label) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (student_id, roll_number, name, _ts(now), direction, float(similarity), source, camera_label))
        return True, now

    def last_seen_since(self, seconds: int, now: Optional[datetime] = None) -> Dict[str, datetime]:
        cutoff = _ts((now or _now()) - timedelta(seconds=seconds))
        with self._conn() as c:
            rows = c.execute("SELECT roll_number, MAX(timestamp) AS last FROM attendance_logs "
                             "WHERE timestamp >= ? GROUP BY roll_number", (cutoff,)).fetchall()
        return {r["roll_number"]: datetime.strptime(r["last"], DATE_FMT) for r in rows}

    @staticmethod
    def _today_start(now: Optional[datetime] = None) -> str:
        return (now or _now()).strftime("%Y-%m-%d") + " 00:00:00"

    def today_unique_count(self, now: Optional[datetime] = None) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(DISTINCT roll_number) FROM attendance_logs WHERE timestamp >= ?",
                             (self._today_start(now),)).fetchone()[0]

    def today_total_scans(self, now: Optional[datetime] = None) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM attendance_logs WHERE timestamp >= ?",
                             (self._today_start(now),)).fetchone()[0]

    def recent_entries(self, limit: int = 25) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT name, roll_number, timestamp, direction, similarity, source "
                             "FROM attendance_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def hourly_counts_today(self, now: Optional[datetime] = None) -> List[Tuple[str, int]]:
        with self._conn() as c:
            rows = c.execute("SELECT substr(timestamp, 12, 2) AS h, COUNT(*) AS n FROM attendance_logs "
                             "WHERE timestamp >= ? GROUP BY h ORDER BY h", (self._today_start(now),)).fetchall()
        return [(f"{r['h']}:00", r["n"]) for r in rows]

    def all_logs(self, limit: int = 100000) -> List[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT id, timestamp, roll_number, name, direction, similarity, source "
                             "FROM attendance_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def today_known_count(self, now: Optional[datetime] = None) -> int:
        """Count unique known persons (enrolled students) detected today."""
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(DISTINCT roll_number) FROM attendance_logs "
                "WHERE timestamp >= ? AND student_id IS NOT NULL",
                (self._today_start(now),)).fetchone()[0]

    def today_unknown_count(self, now: Optional[datetime] = None) -> int:
        """Count unique unknown persons (not enrolled) detected today."""
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(DISTINCT roll_number) FROM attendance_logs "
                "WHERE timestamp >= ? AND student_id IS NULL",
                (self._today_start(now),)).fetchone()[0]

    # ----------------------------------------------------------- Search & Filter
    def search_logs(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                    roll_number: Optional[str] = None, name: Optional[str] = None,
                    camera_label: Optional[str] = None, limit: int = 1000) -> List[dict]:
        """Search attendance logs with filters."""
        with self._conn() as c:
            query = "SELECT * FROM attendance_logs WHERE 1=1"
            params = []
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date + " 23:59:59")
            if roll_number:
                query += " AND roll_number LIKE ?"
                params.append(f"%{roll_number}%")
            if name:
                query += " AND name LIKE ?"
                params.append(f"%{name}%")
            if camera_label:
                query += " AND camera_label = ?"
                params.append(camera_label)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_student_profile(self, roll_number: str) -> Optional[dict]:
        """Get complete student profile with statistics."""
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM students WHERE roll_number = ?",
                (roll_number.strip().upper(),)
            ).fetchone()
            if not row:
                return None
            profile = dict(row)
            # Add attendance stats
            total = c.execute(
                "SELECT COUNT(*) FROM attendance_logs WHERE roll_number = ?",
                (roll_number.strip().upper(),)
            ).fetchone()[0]
            profile['total_attendance'] = total
            return profile

    def get_attendance_percentage(self, roll_number: str, days: int = 30) -> float:
        """Calculate attendance percentage for a student."""
        cutoff = _ts((_now() - timedelta(days=days)))
        with self._conn() as c:
            attended = c.execute(
                "SELECT COUNT(DISTINCT DATE(timestamp)) FROM attendance_logs "
                "WHERE roll_number = ? AND timestamp >= ?",
                (roll_number.strip().upper(), cutoff)
            ).fetchone()[0]
        return (attended / days * 100) if days > 0 else 0.0

    # ----------------------------------------------------------- Analytics
    def get_peak_hours(self, days: int = 7) -> List[Tuple[int, int]]:
        """Get peak attendance hours over the last N days."""
        cutoff = _ts((_now() - timedelta(days=days)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT CAST(substr(timestamp, 12, 2) AS INTEGER) AS hour, COUNT(*) AS count "
                "FROM attendance_logs WHERE timestamp >= ? "
                "GROUP BY hour ORDER BY count DESC",
                (cutoff,)
            ).fetchall()
        return [(r['hour'], r['count']) for r in rows]

    def get_absent_students(self, days: int = 7) -> List[dict]:
        """Get students who haven't attended in the last N days."""
        cutoff = _ts((_now() - timedelta(days=days)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT s.roll_number, s.name, s.department, s.batch "
                "FROM students s WHERE s.roll_number NOT IN "
                "(SELECT DISTINCT roll_number FROM attendance_logs WHERE timestamp >= ?)",
                (cutoff,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_late_arrivals(self, date: Optional[str] = None, threshold_hour: int = 9) -> List[dict]:
        """Get students who arrived after a certain hour."""
        if not date:
            date = _now().strftime("%Y-%m-%d")
        with self._conn() as c:
            rows = c.execute(
                "SELECT roll_number, name, timestamp, "
                "CAST(substr(timestamp, 12, 2) AS INTEGER) AS hour "
                "FROM attendance_logs "
                "WHERE DATE(timestamp) = ? AND CAST(substr(timestamp, 12, 2) AS INTEGER) >= ? "
                "ORDER BY timestamp",
                (date, threshold_hour)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_attendance_trends(self, days: int = 30) -> List[Tuple[str, int, int]]:
        """Get daily attendance trends (date, unique_count, total_scans)."""
        cutoff = _ts((_now() - timedelta(days=days)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT DATE(timestamp) AS date, "
                "COUNT(DISTINCT roll_number) AS unique_count, "
                "COUNT(*) AS total_scans "
                "FROM attendance_logs WHERE timestamp >= ? "
                "GROUP BY DATE(timestamp) ORDER BY date",
                (cutoff,)
            ).fetchall()
        return [(r['date'], r['unique_count'], r['total_scans']) for r in rows]

    def get_camera_stats(self) -> List[dict]:
        """Get statistics per camera."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT camera_label, COUNT(*) AS total, "
                "COUNT(DISTINCT roll_number) AS unique_persons "
                "FROM attendance_logs GROUP BY camera_label"
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- Audit & Security
    def log_audit(self, user: str, action: str, details: str = "", ip_address: str = "") -> None:
        """Log admin action for audit trail."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit_logs(timestamp, user, action, details, ip_address) VALUES(?,?,?,?,?)",
                (_ts(_now()), user, action, details, ip_address)
            )

    def get_audit_logs(self, limit: int = 100) -> List[dict]:
        """Get recent audit logs."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- Health Monitoring
    def log_health_metric(self, metric: str, value: float) -> None:
        """Log system health metric."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO system_health(timestamp, metric, value) VALUES(?,?,?)",
                (_ts(_now()), metric, value)
            )

    def get_health_metrics(self, metric: str, hours: int = 24) -> List[Tuple[str, float]]:
        """Get health metrics for the last N hours."""
        cutoff = _ts((_now() - timedelta(hours=hours)))
        with self._conn() as c:
            rows = c.execute(
                "SELECT timestamp, value FROM system_health "
                "WHERE metric = ? AND timestamp >= ? ORDER BY timestamp",
                (metric, cutoff)
            ).fetchall()
        return [(r['timestamp'], r['value']) for r in rows]

    # ----------------------------------------------------------- Bulk Operations
    def bulk_import_students(self, students_data: List[dict]) -> Tuple[int, int, List[str]]:
        """Bulk import students from CSV data. Returns (success_count, error_count, error_messages)."""
        success, errors, error_msgs = 0, 0, []
        for data in students_data:
            try:
                # This would need actual face embeddings - placeholder for now
                # In practice, you'd need photos or use a default embedding
                roll = data.get('roll_number', '').strip().upper()
                name = data.get('name', '').strip()
                if not roll or not name:
                    errors += 1
                    error_msgs.append(f"Missing roll_number or name for entry")
                    continue
                # You would need to handle embeddings properly in real implementation
                # For now, just update metadata if student exists
                with self._conn() as c:
                    existing = c.execute("SELECT id FROM students WHERE roll_number=?", (roll,)).fetchone()
                    if existing:
                        c.execute(
                            "UPDATE students SET email=?, phone=?, department=?, batch=?, expected_time=? WHERE roll_number=?",
                            (data.get('email', ''), data.get('phone', ''), data.get('department', ''),
                             data.get('batch', ''), data.get('expected_time', ''), roll)
                        )
                        success += 1
                    else:
                        # Cannot create without embeddings
                        error_msgs.append(f"Student {roll} does not exist - enroll with photos first")
                        errors += 1
            except Exception as e:
                errors += 1
                error_msgs.append(f"Error importing {data.get('roll_number', 'unknown')}: {str(e)}")
        return success, errors, error_msgs


def init_db(path: str = DB_PATH) -> None:
    conn = sqlite3.connect(path, timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
