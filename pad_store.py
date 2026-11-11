"""
pad_store.py - additive schema + helpers for presentation-attack-detection data.

Adds (never drops or rewrites anything):
  * table pad_events(id, timestamp, camera_label, track_id, state, real_prob, spoof_prob, model_id,
                     student_id NULL, flagged, note)
  * nullable columns pad_state, pad_score on attendance_logs
Existing rows are untouched. All helpers swallow DB errors into logging: PAD bookkeeping must never
break the recognition loop.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Optional

from config import DATE_FMT, DB_PATH

log = logging.getLogger("pad_store")

_DDL = """
CREATE TABLE IF NOT EXISTS pad_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    camera_label TEXT,
    track_id     INTEGER,
    state        TEXT NOT NULL,
    real_prob    REAL,
    spoof_prob   REAL,
    model_id     TEXT,
    student_id   INTEGER,
    flagged      INTEGER NOT NULL DEFAULT 0,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pad_events_ts ON pad_events(timestamp);
"""


def ensure_pad_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(attendance_logs)")}
    for name, typ in (("pad_state", "TEXT"), ("pad_score", "REAL")):
        if name not in cols:
            conn.execute(f"ALTER TABLE attendance_logs ADD COLUMN {name} {typ}")


def migrate_pad_schema(db_path: str = DB_PATH, backup: bool = True) -> Optional[str]:
    """Idempotent. Copies the database to data/backups/ first. Returns the backup path (or None)."""
    if not os.path.exists(db_path):
        return None
    backup_path = None
    if backup:
        folder = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(folder, exist_ok=True)
        backup_path = os.path.join(folder, f"pre_pad_migration_{datetime.now():%Y%m%d_%H%M%S}.db")
        shutil.copy2(db_path, backup_path)
    conn = sqlite3.connect(db_path, timeout=15)
    try:
        ensure_pad_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return backup_path


def record_pad_event(db_path: str, *, camera_label: str, track_id: int, state: str,
                     real_prob: Optional[float], spoof_prob: Optional[float], model_id: str,
                     student_id: Optional[int] = None, flagged: bool = False, note: str = "") -> None:
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        try:
            ensure_pad_schema(conn)
            conn.execute(
                "INSERT INTO pad_events(timestamp, camera_label, track_id, state, real_prob, spoof_prob, "
                "model_id, student_id, flagged, note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().strftime(DATE_FMT), camera_label, track_id, state, real_prob, spoof_prob,
                 model_id, student_id, 1 if flagged else 0, note))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.exception("could not record pad_event")


def annotate_attendance(db_path: str, roll_number: str, pad_state: str, pad_score: Optional[float]) -> None:
    """Stamp the newest attendance row of this student with the PAD outcome that allowed it."""
    try:
        conn = sqlite3.connect(db_path, timeout=15)
        try:
            ensure_pad_schema(conn)
            conn.execute(
                "UPDATE attendance_logs SET pad_state=?, pad_score=? WHERE id=("
                "SELECT MAX(id) FROM attendance_logs WHERE roll_number=?)", (pad_state, pad_score, roll_number))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.exception("could not annotate attendance row with PAD state")
