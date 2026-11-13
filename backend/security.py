"""
backend/security.py - framework-free auth primitives (no FastAPI, no Streamlit; never imports auth.py).

  * Argon2id password hashing (argon2-cffi), injectable for tests
  * web_users / web_sessions tables (additive; the legacy `users` table is left untouched)
  * server-side sessions: random token in an HTTP-only cookie, only its SHA-256 stored
  * per-session CSRF token, login rate limiting, constant-time comparisons
  * legacy SHA-256 users are migrated WITHOUT a password: they must be given a new one by an admin.
    No default credentials exist anywhere; the first admin is created through a one-time setup token.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Deque, Dict, Optional

ROLES = ("admin", "operator", "student")
LEGACY_ROLE_MAP = {"admin": "admin", "viewer": "operator", "operator": "operator", "student": "student"}
MIN_PASSWORD_LEN = 10
_TS = "%Y-%m-%d %H:%M:%S"

DDL = """
CREATE TABLE IF NOT EXISTS web_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT,
    role          TEXT NOT NULL,
    roll_number   TEXT,
    must_reset    INTEGER NOT NULL DEFAULT 0,
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    csrf       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


class AuthError(Exception):
    status = 401


class Forbidden(AuthError):
    status = 403


class RateLimited(AuthError):
    status = 429

    def __init__(self, retry_after: int):
        super().__init__(f"Too many attempts. Try again in {retry_after}s.")
        self.retry_after = retry_after


class BadRequest(AuthError):
    status = 400


class Conflict(AuthError):
    status = 409


class NotFound(AuthError):
    status = 404


# ------------------------------------------------------------------------------------ hashing
class Argon2Hasher:
    def __init__(self):
        from argon2 import PasswordHasher          # argon2-cffi (requirements-api.txt)
        from argon2 import exceptions
        self._ph, self._exc = PasswordHasher(), exceptions

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, stored: str, password: str) -> bool:
        try:
            return self._ph.verify(stored, password)
        except (self._exc.VerifyMismatchError, self._exc.InvalidHashError, self._exc.VerificationError):
            return False

    def needs_rehash(self, stored: str) -> bool:
        try:
            return self._ph.check_needs_rehash(stored)
        except Exception:
            return False


# ------------------------------------------------------------------------------------ rate limit
class RateLimiter:
    """Sliding-window failure counter. Keys are e.g. 'ip|username' and 'ip'."""

    def __init__(self, limits: Dict[str, tuple], clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, kind: str, key: str) -> None:
        max_fail, window = self.limits[kind]
        now = self.clock()
        with self._lock:
            q = self._hits[f"{kind}:{key}"]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= max_fail:
                raise RateLimited(int(window - (now - q[0])) + 1)

    def fail(self, kind: str, key: str) -> None:
        with self._lock:
            self._hits[f"{kind}:{key}"].append(self.clock())

    def reset(self, kind: str, key: str) -> None:
        with self._lock:
            self._hits.pop(f"{kind}:{key}", None)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now()


class AuthService:
    def __init__(self, db_path: str, hasher=None, *, setup_token: Optional[str] = None,
                 session_ttl_hours: float = 8.0, limiter: Optional[RateLimiter] = None, clock=_now):
        self.db_path = db_path
        self.hasher = hasher or Argon2Hasher()
        self.setup_token = setup_token or secrets.token_urlsafe(18)
        self.ttl = timedelta(hours=session_ttl_hours)
        self.limiter = limiter or RateLimiter({"user": (5, 600), "ip": (30, 600)})
        self.clock = clock
        self._dummy = self.hasher.hash(secrets.token_urlsafe(12))      # equalises timing for unknown users
        self.ensure_schema()
        self.migrate_legacy_users()

    # ---- db
    @contextmanager
    def _c(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with self._c() as c:
            c.executescript(DDL)

    def migrate_legacy_users(self) -> int:
        """Copy legacy `users` rows (username 'name:salt', SHA-256) into web_users WITHOUT credentials."""
        n = 0
        with self._c() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone():
                return 0
            for r in c.execute("SELECT username, role, created_at FROM users").fetchall():
                name = r["username"].split(":", 1)[0].strip()
                if not name:
                    continue
                role = LEGACY_ROLE_MAP.get(r["role"], "operator")
                cur = c.execute("INSERT OR IGNORE INTO web_users(username, password_hash, role, roll_number, "
                                "must_reset, created_at) VALUES(?,?,?,?,1,?)",
                                (name, None, role, name.upper() if role == "student" else None,
                                 r["created_at"] or self.clock().strftime(_TS)))
                n += cur.rowcount
        return n

    # ---- users
    @staticmethod
    def public(row) -> dict:
        return {"username": row["username"], "role": row["role"], "roll_number": row["roll_number"]}

    def get_user(self, username: str):
        with self._c() as c:
            return c.execute("SELECT * FROM web_users WHERE username=?", (username,)).fetchone()

    def _check_password_policy(self, pw: str) -> None:
        if len(pw) < MIN_PASSWORD_LEN:
            raise BadRequest(f"Password must be at least {MIN_PASSWORD_LEN} characters.")

    def setup_required(self) -> bool:
        with self._c() as c:
            return c.execute("SELECT 1 FROM web_users WHERE role='admin' AND password_hash IS NOT NULL "
                             "AND disabled=0 LIMIT 1").fetchone() is None

    def setup(self, token: str, username: str, password: str, ip: str = "") -> dict:
        self.limiter.check("ip", ip)
        if not self.setup_required():
            raise Forbidden("Setup already completed.")
        if not hmac.compare_digest(token.encode(), self.setup_token.encode()):
            self.limiter.fail("ip", ip)
            raise Forbidden("Invalid setup token.")
        username = username.strip()
        if not username or ":" in username:
            raise BadRequest("Invalid username.")
        self._check_password_policy(password)
        h = self.hasher.hash(password)
        with self._c() as c:
            row = c.execute("SELECT id, role FROM web_users WHERE username=?", (username,)).fetchone()
            if row:
                c.execute("UPDATE web_users SET password_hash=?, role='admin', must_reset=0, disabled=0 WHERE id=?",
                          (h, row["id"]))
            else:
                c.execute("INSERT INTO web_users(username, password_hash, role, must_reset, created_at) "
                          "VALUES(?,?,'admin',0,?)", (username, h, self.clock().strftime(_TS)))
        return self.get_user(username)

    def create_user(self, username: str, role: str, password: str, roll_number: Optional[str] = None,
                    must_reset: bool = False):
        if role not in ROLES:
            raise BadRequest("Invalid role.")
        username = username.strip()
        if not username or ":" in username:
            raise BadRequest("Invalid username.")
        if role == "student" and not roll_number:
            roll_number = username.upper()
        self._check_password_policy(password)
        try:
            with self._c() as c:
                c.execute("INSERT INTO web_users(username, password_hash, role, roll_number, must_reset, created_at) "
                          "VALUES(?,?,?,?,?,?)", (username, self.hasher.hash(password), role,
                                                  (roll_number or "").upper() or None, int(must_reset),
                                                  self.clock().strftime(_TS)))
        except sqlite3.IntegrityError:
            raise Conflict("Username already exists.")
        return self.get_user(username)

    def list_users(self):
        with self._c() as c:
            return c.execute("SELECT * FROM web_users ORDER BY username").fetchall()

    def update_user(self, username: str, *, role=None, disabled=None, roll_number=None, acting: str = ""):
        row = self.get_user(username)
        if not row:
            raise NotFound("No such user.")
        if role is not None and role not in ROLES:
            raise BadRequest("Invalid role.")
        if row["username"].lower() == acting.lower() and (disabled or (role and role != "admin")):
            raise Conflict("You cannot disable or demote your own account.")
        with self._c() as c:
            if role is not None:
                c.execute("UPDATE web_users SET role=? WHERE id=?", (role, row["id"]))
            if disabled is not None:
                c.execute("UPDATE web_users SET disabled=? WHERE id=?", (int(disabled), row["id"]))
                if disabled:
                    c.execute("DELETE FROM web_sessions WHERE user_id=?", (row["id"],))
            if roll_number is not None:
                c.execute("UPDATE web_users SET roll_number=? WHERE id=?", (roll_number.upper() or None, row["id"]))
        return self.get_user(username)

    def delete_user(self, username: str, acting: str = "") -> None:
        if username.lower() == acting.lower():
            raise Conflict("You cannot delete your own account.")
        with self._c() as c:
            if c.execute("DELETE FROM web_users WHERE username=?", (username,)).rowcount == 0:
                raise NotFound("No such user.")

    def temporary_password(self, username: str) -> str:
        row = self.get_user(username)
        if not row:
            raise NotFound("No such user.")
        tmp = secrets.token_urlsafe(12)
        with self._c() as c:
            c.execute("UPDATE web_users SET password_hash=?, must_reset=1 WHERE id=?", (self.hasher.hash(tmp), row["id"]))
            c.execute("DELETE FROM web_sessions WHERE user_id=?", (row["id"],))
        return tmp

    # ---- sessions
    def login(self, username: str, password: str, ip: str = "") -> dict:
        ukey = f"{ip}|{username.lower()}"
        self.limiter.check("user", ukey)
        self.limiter.check("ip", ip)
        row = self.get_user(username.strip())
        stored = row["password_hash"] if row else None
        ok = self.hasher.verify(stored or self._dummy, password) and stored is not None
        if not ok or row["disabled"]:
            self.limiter.fail("user", ukey)
            self.limiter.fail("ip", ip)
            raise AuthError("Invalid username or password.")
        self.limiter.reset("user", ukey)
        if self.hasher.needs_rehash(stored):
            with self._c() as c:
                c.execute("UPDATE web_users SET password_hash=? WHERE id=?", (self.hasher.hash(password), row["id"]))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        now = self.clock()
        with self._c() as c:
            c.execute("DELETE FROM web_sessions WHERE expires_at < ?", (now.strftime(_TS),))
            c.execute("INSERT INTO web_sessions(token_hash, user_id, csrf, created_at, expires_at) VALUES(?,?,?,?,?)",
                      (_sha(token), row["id"], csrf, now.strftime(_TS), (now + self.ttl).strftime(_TS)))
        return {"user": self.public(row), "token": token, "csrf": csrf, "must_reset": bool(row["must_reset"])}

    def resolve(self, token: Optional[str]) -> Optional[dict]:
        """Session cookie -> {'user', 'csrf', 'must_reset', 'user_id'} or None (expired/disabled/unknown)."""
        if not token:
            return None
        with self._c() as c:
            r = c.execute("SELECT s.csrf, s.expires_at, u.* FROM web_sessions s JOIN web_users u ON u.id=s.user_id "
                          "WHERE s.token_hash=?", (_sha(token),)).fetchone()
            if not r:
                return None
            if r["expires_at"] < self.clock().strftime(_TS) or r["disabled"]:
                c.execute("DELETE FROM web_sessions WHERE token_hash=?", (_sha(token),))
                return None
        return {"user": self.public(r), "csrf": r["csrf"], "must_reset": bool(r["must_reset"]), "user_id": r["id"]}

    def logout(self, token: Optional[str]) -> None:
        if token:
            with self._c() as c:
                c.execute("DELETE FROM web_sessions WHERE token_hash=?", (_sha(token),))

    def change_password(self, username: str, current: str, new: str) -> None:
        row = self.get_user(username)
        if not row or not row["password_hash"] or not self.hasher.verify(row["password_hash"], current):
            raise AuthError("Current password is incorrect.")
        self._check_password_policy(new)
        if new == current:
            raise BadRequest("New password must differ from the current one.")
        with self._c() as c:
            c.execute("UPDATE web_users SET password_hash=?, must_reset=0 WHERE id=?", (self.hasher.hash(new), row["id"]))

    @staticmethod
    def csrf_ok(session: dict, header_value: Optional[str]) -> bool:
        return bool(header_value) and hmac.compare_digest(session["csrf"].encode(), header_value.encode())


def mask_source(source: str) -> str:
    """Hide credentials in rtsp://user:pass@host/... -> rtsp://***@host/..."""
    if "://" in source and "@" in source.split("://", 1)[1].split("/", 1)[0]:
        scheme, rest = source.split("://", 1)
        hostpart, _, path = rest.partition("/")
        return f"{scheme}://***@{hostpart.rsplit('@', 1)[1]}" + (f"/{path}" if path else "")
    return source
