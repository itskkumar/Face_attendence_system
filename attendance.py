"""
attendance.py - cooldown-aware attendance logger.

`last_seen_dict` is the fast in-memory guard (roll_number -> last logged time).
It is pre-loaded from the database at start-up, so a restart does NOT forget who
was just logged, and the database transaction in Store.log_attendance() is the
final authority when several processes write at once.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Dict, Optional

from database import Store, StudentInfo


class AttendanceLogger:
    def __init__(self, store: Store, cooldown_seconds: int, source: str = "live",
                 clock: Callable[[], datetime] = datetime.now):
        self.store = store
        self.cooldown_seconds = cooldown_seconds
        self.source = source
        self.clock = clock
        self.last_seen_dict: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self.last_seen_dict.update(store.last_seen_since(cooldown_seconds, now=clock()))

    def in_cooldown(self, roll_number: str) -> bool:
        with self._lock:
            last = self.last_seen_dict.get(roll_number)
        return last is not None and (self.clock() - last).total_seconds() < self.cooldown_seconds

    def maybe_log(self, student: StudentInfo, similarity: float, direction: str) -> bool:
        """Log the student unless they are inside the cooldown window. True if a row was written."""
        if self.in_cooldown(student.roll_number):
            return False
        logged, last = self.store.log_attendance(
            student.roll_number, student.name, student.id, similarity, direction,
            self.source, self.cooldown_seconds, now=self.clock())
        if last is not None:
            with self._lock:
                self.last_seen_dict[student.roll_number] = last
        return logged
