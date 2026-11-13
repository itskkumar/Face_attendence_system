import sqlite3

import pytest

from backend import security as S


class FakeHasher:                                     # SIMULATED: fast stand-in for Argon2 in unit tests
    def hash(self, p): return "h$" + p[::-1]
    def verify(self, stored, p): return stored == "h$" + p[::-1]
    def needs_rehash(self, stored): return False


@pytest.fixture
def auth(tmp_path):
    db = str(tmp_path / "a.db")
    c = sqlite3.connect(db)
    c.execute("create table users(id integer primary key, username text, password_hash text, role text, created_at text)")
    c.execute("insert into users(username,password_hash,role,created_at) values('admin:salt','x'*1,'admin','2025-01-01')")
    c.execute("insert into users(username,password_hash,role,created_at) values('karan:s2','y','viewer','2025-01-01')")
    c.execute("insert into users(username,password_hash,role,created_at) values('21CS001:s3','z','student','2025-01-01')")
    c.commit(); c.close()
    return S.AuthService(db, FakeHasher(), setup_token="TOK")


def test_legacy_users_migrated_without_credentials_and_cannot_login(auth):
    users = {u["username"]: u for u in auth.list_users()}
    assert users["admin"]["password_hash"] is None and users["admin"]["must_reset"] == 1
    assert users["karan"]["role"] == "operator" and users["21CS001"]["role"] == "student"
    for pw in ("admin123", "x", "", "student123", "21CS001"):
        with pytest.raises(S.AuthError):
            auth.login("admin", pw)
    with pytest.raises(S.AuthError):
        auth.login("21CS001", "21CS001")                 # the old roll-number-as-password is gone


def test_setup_needs_token_and_only_works_once(auth):
    assert auth.setup_required()
    with pytest.raises(S.Forbidden):
        auth.setup("WRONG", "root", "correct horse battery")
    with pytest.raises(S.BadRequest):
        auth.setup("TOK", "root", "short")
    auth.setup("TOK", "root", "correct horse battery")
    assert not auth.setup_required()
    with pytest.raises(S.Forbidden):
        auth.setup("TOK", "other", "correct horse battery")
    assert auth.login("root", "correct horse battery")["user"]["role"] == "admin"


def test_session_lifecycle_csrf_and_expiry(tmp_path):
    from datetime import datetime, timedelta
    t = {"now": datetime(2026, 1, 1, 9, 0, 0)}
    a = S.AuthService(str(tmp_path / "b.db"), FakeHasher(), setup_token="T", clock=lambda: t["now"], session_ttl_hours=1)
    a.setup("T", "root", "correct horse battery")
    s = a.login("root", "correct horse battery")
    r = a.resolve(s["token"])
    assert r["user"]["username"] == "root" and a.csrf_ok(r, s["csrf"]) and not a.csrf_ok(r, "nope") and not a.csrf_ok(r, None)
    assert a.resolve("garbage") is None and a.resolve(None) is None
    t["now"] += timedelta(hours=2)
    assert a.resolve(s["token"]) is None                  # expired
    s2 = a.login("root", "correct horse battery")
    a.logout(s2["token"])
    assert a.resolve(s2["token"]) is None


def test_session_token_is_stored_hashed(auth):
    auth.setup("TOK", "root", "correct horse battery")
    s = auth.login("root", "correct horse battery")
    c = sqlite3.connect(auth.db_path)
    assert s["token"] not in str(c.execute("select * from web_sessions").fetchall())


def test_login_rate_limit_and_reset_on_success(auth):
    auth.setup("TOK", "root", "correct horse battery")
    for _ in range(5):
        with pytest.raises(S.AuthError):
            auth.login("root", "wrong password!", ip="1.2.3.4")
    with pytest.raises(S.RateLimited) as e:
        auth.login("root", "correct horse battery", ip="1.2.3.4")   # even the right password is blocked
    assert e.value.status == 429 and e.value.retry_after > 0
    assert auth.login("root", "correct horse battery", ip="9.9.9.9")  # other client unaffected


def test_unknown_user_and_wrong_password_look_identical(auth):
    auth.setup("TOK", "root", "correct horse battery")
    msgs = set()
    for u, p in [("root", "bad bad bad bad"), ("ghost", "bad bad bad bad")]:
        with pytest.raises(S.AuthError) as e:
            auth.login(u, p)
        msgs.add(str(e.value))
    assert len(msgs) == 1


def test_disabled_user_cannot_login_and_sessions_die(auth):
    auth.setup("TOK", "root", "correct horse battery")
    auth.create_user("op", "operator", "operator-password-1")
    s = auth.login("op", "operator-password-1")
    auth.update_user("op", disabled=True, acting="root")
    assert auth.resolve(s["token"]) is None
    with pytest.raises(S.AuthError):
        auth.login("op", "operator-password-1")


def test_cannot_demote_or_delete_self(auth):
    auth.setup("TOK", "root", "correct horse battery")
    with pytest.raises(S.Conflict):
        auth.update_user("root", role="operator", acting="root")
    with pytest.raises(S.Conflict):
        auth.delete_user("root", acting="root")


def test_temporary_password_forces_reset_and_change_password(auth):
    auth.setup("TOK", "root", "correct horse battery")
    auth.create_user("op", "operator", "operator-password-1")
    tmp = auth.temporary_password("op")
    s = auth.login("op", tmp)
    assert s["must_reset"]
    with pytest.raises(S.AuthError):
        auth.change_password("op", "wrong", "brand new password 1")
    auth.change_password("op", tmp, "brand new password 1")
    assert not auth.login("op", "brand new password 1")["must_reset"]


def test_mask_source():
    assert S.mask_source("rtsp://admin:secret@10.0.0.5:554/stream1") == "rtsp://***@10.0.0.5:554/stream1"
    assert "secret" not in S.mask_source("rtsp://admin:secret@10.0.0.5/s")
    assert S.mask_source("http://10.1.1.1:8080") == "http://10.1.1.1:8080"
    assert S.mask_source("0") == "0"
