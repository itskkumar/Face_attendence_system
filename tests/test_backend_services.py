import json
import os
import sqlite3

import pytest

import pad_store
from backend import services as V
from backend.security import BadRequest, Conflict, NotFound
from database import Store
from test_pipeline_logic import emb


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    with s._conn() as c:
        pad_store.ensure_pad_schema(c)
    s.add_student("R1", "Asha", [emb(0)], email="a@x.com")
    s.add_student("R2", "Bimal", [emb(1)])
    for i in range(30):
        s.log_attendance("R1" if i % 2 else "R2", "Asha" if i % 2 else "Bimal", None, 0.9, "ENTRY", "t", 0, camera_label="cam" + str(i % 3))
    return s


def test_attendance_pagination_and_filters(store):
    p1 = V.list_attendance(store, {}, 1, 10)
    assert p1["total"] == 30 and len(p1["items"]) == 10 and p1["page_size"] == 10
    p3 = V.list_attendance(store, {}, 3, 10)
    assert len(p3["items"]) == 10 and {r["id"] for r in p1["items"]}.isdisjoint({r["id"] for r in p3["items"]})
    assert V.list_attendance(store, {"roll_number": "R1"}, 1, 50)["total"] == 15
    assert V.list_attendance(store, {"camera_label": "cam0"}, 1, 50)["total"] == 10
    assert V.list_attendance(store, {}, 1, 9999)["page_size"] == 200
    assert {"pad_state", "pad_score"} <= set(p1["items"][0])


def test_attendance_works_before_pad_migration(tmp_path):
    s = Store(str(tmp_path / "old.db"))
    s.add_student("R1", "Asha", [emb(0)]); s.log_attendance("R1", "Asha", None, 0.9, "ENTRY", "t", 0)
    it = V.list_attendance(s, {}, 1, 5)["items"][0]
    assert it["pad_state"] is None


def test_csv_export_neutralises_formula_injection(store):
    with store._conn() as c:
        c.execute("update attendance_logs set name='=cmd|calc' where id=1")
    out = V.attendance_csv(store, {})
    assert "'=cmd|calc" in out and out.splitlines()[0].startswith("id,roll_number")


def test_students_never_expose_embeddings(store):
    page = V.list_students(store, "", 1, 10)
    assert page["total"] == 2 and "embedding" not in json.dumps(page).lower()
    s = V.get_student(store, "r1")
    assert s["template_count"] == 1 and "embedding" not in s and s["email"] == "a@x.com"
    with pytest.raises(NotFound):
        V.get_student(store, "NOPE")


def test_student_update_delete_import(store):
    V.update_student(store, "R1", {"name": "Asha K", "department": "CSE"})
    assert V.get_student(store, "R1")["department"] == "CSE"
    with pytest.raises(BadRequest):
        V.update_student(store, "R1", {"name": " "})
    r = V.import_students_csv(store, "roll_number,name,email\nR1,Asha,new@x.com\nR9,Ghost,\n")
    assert r["updated"] == 1 and r["skipped"] == 1 and r["errors"]
    with pytest.raises(BadRequest):
        V.import_students_csv(store, "foo,bar\n1,2\n")
    V.delete_student(store, "R2")
    with pytest.raises(NotFound):
        V.delete_student(store, "R2")


def test_dashboard_has_real_numbers(store):
    d = V.dashboard(store)
    assert d["today_scans"] >= 0 and d["enrolled_students"] == 2 and len(d["recent"]) == 15
    assert {"hourly", "trends", "peak_hours", "late_arrivals"} <= set(d)


def test_student_summary_scoped_to_roll(store):
    s = V.my_summary(store, "R1")
    assert all(r["roll_number"] == "R1" for r in s["today"])


def test_camera_repo_masks_credentials_and_keeps_source(tmp_path):
    repo = V.CameraRepo(str(tmp_path / "cameras.json"))
    out = repo.upsert(None, "gate", "rtsp", "rtsp://admin:hunter2@10.0.0.9:554/s1", "front", True)
    assert "hunter2" not in json.dumps(out) and out["source_masked"].startswith("rtsp://***@10.0.0.9")
    assert "hunter2" not in json.dumps(repo.list())
    repo.upsert("gate", "gate", "rtsp", None, "renamed", True)             # omitted source keeps the old one
    assert repo.get_source("gate") == ("rtsp", "rtsp://admin:hunter2@10.0.0.9:554/s1")
    with pytest.raises(Conflict):
        repo.upsert(None, "gate", "rtsp", "rtsp://x", "", True)
    with pytest.raises(BadRequest):
        repo.upsert(None, "bad/name", "rtsp", "rtsp://x", "", True)
    assert oct(os.stat(repo.path).st_mode & 0o777) == "0o600"
    repo.delete("gate")
    with pytest.raises(NotFound):
        repo.delete("gate")


def test_camera_repo_reads_the_shipped_format(tmp_path):
    p = tmp_path / "cameras.json"
    p.write_text(json.dumps({"gh": {"type": "RTSP Stream", "source": "http://10.0.0.1:8080", "description": "", "enabled": True}}))
    c = V.CameraRepo(str(p)).list()[0]
    assert c["id"] == "gh" and c["type"] == "rtsp" and c["status"] == "idle"


def test_security_alerts_and_audit(store):
    store.log_audit("root", "login", "ok")
    assert V.audit_page(store)["total"] == 1
    pad_store.record_pad_event(store.path, camera_label="c", track_id=1, state="SPOOF", real_prob=0.1, spoof_prob=0.9,
                               model_id="m", flagged=True, note="x")
    a = V.security_alerts(store)
    assert a["spoof_today"] == 1 and a["pad_events"][0]["flagged"] == 1


def test_system_metrics_shape():
    m = V.system_metrics()
    assert set(m) == {"cpu_percent", "ram_percent", "ram_used_mb"}
