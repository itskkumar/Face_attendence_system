"""
HTTP/WebSocket tests for backend/app.py. They need `pip install -r requirements-api.txt` (fastapi, httpx) and
are SKIPPED when FastAPI is not installed - in the authoring sandbox it was not, so these were NEVER RUN there.
Run them on your machine: python -m pytest tests/test_backend_api.py -q
"""
import json

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (requirements-api.txt) - API tests not run")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient                          # noqa: E402

import pad_store                                                   # noqa: E402
from backend import security as S                                  # noqa: E402
from backend import services as V                                  # noqa: E402
from backend.app import COOKIE, create_app                         # noqa: E402
from database import Store                                         # noqa: E402
from test_backend_security import FakeHasher                       # noqa: E402
from test_pipeline_logic import emb                                # noqa: E402

ORIGIN = {"Origin": "http://localhost:3000"}


class FakeWorker:                                                  # SIMULATED worker link
    status = {"running": False, "fps": 0, "pad": {"state": "NOT_CONFIGURED", "reason": "x", "model_id": "none", "models": []},
              "liveness_mode": "off", "provider": "", "proc_ms": 0, "det_ms": 0, "rec_ms": 0, "pad_ms": 0, "settings": {}}
    events, event_seq, frame, frame_seq, viewers = [], 0, None, 0, 0
    def available(self): return True
    def refresh_status(self): return self.status
    def send(self, cmd): self.last = cmd
    def viewer(self, d): pass
    def rpc(self, name, *a, timeout=0): return {"engine_ready": True, "pad": self.status["pad"], "liveness_mode": "off", "require_liveness": False}


@pytest.fixture
def ctx(tmp_path):
    store = Store(str(tmp_path / "a.db"))
    with store._conn() as c:
        pad_store.ensure_pad_schema(c)
    store.add_student("R1", "Asha", [emb(0)]); store.add_student("R2", "Bimal", [emb(1)])
    for i in range(5):
        store.log_attendance("R1", "Asha", None, 0.9, "ENTRY", "t", 0)
        store.log_attendance("R2", "Bimal", None, 0.9, "ENTRY", "t", 0)
    auth = S.AuthService(store.path, FakeHasher(), setup_token="TOK")
    auth.setup("TOK", "root", "correct horse battery")
    auth.create_user("op", "operator", "operator-password-1")
    auth.create_user("R1", "student", "student-password-1", "R1")
    app = create_app(auth=auth, store=store, worker=FakeWorker(), cameras=V.CameraRepo(str(tmp_path / "c.json")),
                     allowed_origins=["http://localhost:3000"], start_background=False)
    with TestClient(app, base_url="http://localhost:3000") as client:
        yield client, auth


def login(client, user, pw):
    r = client.post("/api/auth/login", json={"username": user, "password": pw}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return {**ORIGIN, "X-CSRF-Token": r.json()["csrf_token"]}


def test_unauthenticated_is_401_everywhere(ctx):
    c, _ = ctx
    for path in ("/api/dashboard", "/api/attendance", "/api/students", "/api/users", "/api/cameras", "/api/system", "/api/me/profile"):
        assert c.get(path).status_code == 401, path


def test_login_cookie_flags_and_csrf(ctx):
    c, _ = ctx
    r = c.post("/api/auth/login", json={"username": "root", "password": "correct horse battery"}, headers=ORIGIN)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and COOKIE in cookie
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout", headers=ORIGIN).status_code == 403                          # no CSRF header
    assert c.post("/api/auth/logout", headers={"Origin": "http://evil.example", "X-CSRF-Token": r.json()["csrf_token"]}).status_code == 403
    assert c.post("/api/auth/logout", headers={**ORIGIN, "X-CSRF-Token": r.json()["csrf_token"]}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_role_matrix(ctx):
    c, _ = ctx
    h = login(c, "op", "operator-password-1")
    assert c.get("/api/dashboard").status_code == 200 and c.get("/api/students").status_code == 200
    assert c.get("/api/users").status_code == 403 and c.get("/api/inspector").status_code == 403
    assert c.post("/api/live/stop", headers=h).status_code == 403 and c.delete("/api/students/R1", headers=h).status_code == 403
    assert c.get("/api/me/profile").status_code == 403
    c.cookies.clear()
    h = login(c, "R1", "student-password-1")
    assert c.get("/api/dashboard").status_code == 403 and c.get("/api/attendance").status_code == 403
    assert c.get("/api/students").status_code == 403


def test_student_sees_only_own_rows(ctx):
    c, _ = ctx
    login(c, "R1", "student-password-1")
    page = c.get("/api/me/attendance?page_size=100&roll_number=R2").json()
    assert page["total"] == 5 and {r["roll_number"] for r in page["items"]} == {"R1"}
    assert c.get("/api/me/profile").json()["roll_number"] == "R1"


def test_pagination_and_filters(ctx):
    c, _ = ctx
    login(c, "root", "correct horse battery")
    p = c.get("/api/attendance?page=2&page_size=4").json()
    assert p["total"] == 10 and len(p["items"]) == 4 and p["page"] == 2
    assert c.get("/api/attendance?roll_number=R2").json()["total"] == 5
    assert c.get("/api/attendance?start_date=bad").status_code == 422


def test_no_embeddings_or_credentials_in_any_get(ctx):
    c, _ = ctx
    h = login(c, "root", "correct horse battery")
    c.post("/api/cameras", json={"name": "gate", "type": "rtsp", "source": "rtsp://u:hunter2@10.0.0.2/s", "description": "", "enabled": True}, headers=h)
    for path in ("/api/dashboard", "/api/attendance", "/api/students", "/api/students/R1", "/api/cameras", "/api/system",
                 "/api/inspector", "/api/security/alerts", "/api/audit", "/api/users", "/api/live/status", "/api/live/events",
                 "/api/analytics", "/api/attendance/export.csv"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.text)
        low = r.text.lower()
        assert "embedding" not in low and "hunter2" not in low, path


def test_rate_limit_returns_429(ctx):
    c, _ = ctx
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "root", "password": "nope nope nope"}, headers=ORIGIN).status_code == 401
    r = c.post("/api/auth/login", json={"username": "root", "password": "correct horse battery"}, headers=ORIGIN)
    assert r.status_code == 429 and "retry-after" in r.headers


def test_setup_is_closed_once_an_admin_exists(ctx):
    c, _ = ctx
    assert c.get("/api/auth/status").json() == {"setup_required": False}
    r = c.post("/api/auth/setup", json={"setup_token": "TOK", "username": "x", "password": "another long password"}, headers=ORIGIN)
    assert r.status_code == 403


def test_must_reset_user_is_confined_to_password_change(ctx):
    c, auth = ctx
    tmp = auth.temporary_password("op")
    h = login(c, "op", tmp)
    assert c.get("/api/dashboard").status_code == 403
    assert c.get("/api/auth/me").json()["must_reset_password"] is True
    assert c.post("/api/auth/change-password", json={"current_password": tmp, "new_password": "brand new password 1"}, headers=h).status_code == 200
    assert c.get("/api/dashboard").status_code == 200


def test_audit_entries_written(ctx):
    c, _ = ctx
    h = login(c, "root", "correct horse battery")
    c.post("/api/cameras", json={"name": "g2", "type": "webcam", "source": "0", "description": "", "enabled": True}, headers=h)
    actions = {a["action"] for a in c.get("/api/audit").json()["items"]}
    assert {"login", "camera_added"} <= actions


def test_websocket_auth_and_origin(ctx):
    c, _ = ctx
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/ws/events", headers=ORIGIN):
            pass
    assert e.value.code == 4401
    login(c, "root", "correct horse battery")
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/ws/events", headers={"Origin": "http://evil.example"}):
            pass
    assert e.value.code == 4403
    with c.websocket_connect("/ws/events", headers=ORIGIN) as ws:
        assert ws.receive_json()["kind"] == "status"
    c.cookies.clear(); login(c, "R1", "student-password-1")
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/ws/preview", headers=ORIGIN):
            pass
    assert e.value.code == 4403


def test_live_file_source_must_be_an_upload(ctx):
    c, _ = ctx
    h = login(c, "root", "correct horse battery")
    assert c.post("/api/live/start", json={"source": "file", "file_path": "/etc/passwd"}, headers=h).status_code == 422
    assert c.put("/api/live/settings", json={"liveness_mode": "magic"}, headers=h).status_code == 422
