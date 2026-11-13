"""Worker behaviour with the scripted fake engine (SIMULATED models) - lifecycle, bounds, single instance, transport."""
import threading
import time

import cv2
import numpy as np
import pytest

import antispoof
from backend import worker as W
from config import DEFAULT_SETTINGS
from database import Store
from test_pipeline_logic import Person, emb, make


class FakeSource:
    def __init__(self, scene):
        self.scene, self.i, self.last_error, self.released = scene, 0, None, False

    def read(self):
        img = self.scene.render()
        self.scene.f += 1
        return True, img

    def release(self): self.released = True


def make_worker(tmp_path, persons, out, **kw):
    store = Store(str(tmp_path / "w.db"))
    store.add_student("R0", "Asha", [emb(0)])
    scene, _pipe, clock = make(store, persons)
    engine = _pipe.engine
    made = {"engines": 0, "pads": 0}

    def engine_factory(s):
        made["engines"] += 1
        return engine

    def pad_factory(s):
        made["pads"] += 1
        return antispoof.NullPAD()

    w = W.GateWorker(store, DEFAULT_SETTINGS, lambda cid: ("rtsp", "rtsp://u:SECRET@h/x"), engine_factory, pad_factory,
                     lambda kind, target, loop=False: FakeSource(scene), out.append, **kw)
    return w, store, made, scene


def test_apply_tuning_validates():
    s = W.apply_tuning(DEFAULT_SETTINGS, {"similarity_threshold": 0.5, "liveness_mode": "minifas"})
    assert s.similarity_threshold == 0.5 and s.liveness_mode == "minifas" and s.min_votes == DEFAULT_SETTINGS.min_votes
    for bad in ({"similarity_threshold": 5}, {"liveness_mode": "magic"}, {"min_votes": 1}, {"gate_line_ratio": 0}):
        with pytest.raises(ValueError):
            W.apply_tuning(DEFAULT_SETTINGS, bad)


def test_one_engine_and_pad_per_process_across_restarts(tmp_path):
    out = []
    w, store, made, scene = make_worker(tmp_path, [Person(0, lambda f: (320, 240))], out)
    for _ in range(3):
        w.handle(("start", {"source": "server_webcam"}))
        assert w.running
        for _ in range(5):
            w.tick()
    w.handle(("settings", {"similarity_threshold": 0.5}))
    assert w.running and w.settings.similarity_threshold == 0.5
    assert made == {"engines": 1, "pads": 1}


def test_preview_only_while_watching_and_capped(tmp_path):
    out = []
    w, *_ = make_worker(tmp_path, [Person(0, lambda f: (320, 240))], out, preview_fps=5, preview_width=320)
    w.handle(("start", {"source": "server_webcam"}))
    for _ in range(10):
        w.tick()
    assert not [m for m in out if m[0] == "frame"]
    w.handle(("watch", True))
    t0 = time.time()
    while time.time() - t0 < 0.6:
        w.tick()
    frames = [m[1] for m in out if m[0] == "frame"]
    assert 1 <= len(frames) <= 5
    f = frames[0]
    img = cv2.imdecode(np.frombuffer(f["jpeg"], np.uint8), 1)
    assert img.shape[1] == 320 and f["width"] == 320
    for t in f["tracks"]:
        assert max(t["bbox"]) <= 320 + 1 and "embedding" not in t


def test_start_failure_is_reported_and_no_url_leaks(tmp_path):
    out = []
    w, *_ = make_worker(tmp_path, [], out)
    w.open_source = lambda *a, **k: type("S", (), {"last_error": "cannot open rtsp://u:SECRET@h/x", "release": lambda s: None})()
    w.handle(("start", {"source": "camera", "camera_id": "gate"}))
    assert not w.running and w.error
    w.handle(("status",))
    assert w.status()["source_label"] == ""


def test_status_never_contains_url(tmp_path):
    out = []
    w, *_ = make_worker(tmp_path, [Person(0, lambda f: (320, 240))], out)
    w.handle(("start", {"source": "camera", "camera_id": "gate"}))
    for _ in range(5):
        w.tick()
    assert "SECRET" not in str(w.status()) and "SECRET" not in str(out)
    assert w.status()["source_label"] == "rtsp" and w.status()["pad"]["state"] == "NOT_CONFIGURED"


def test_browser_source_keeps_only_newest_frame():
    b = W.BrowserSource()
    ok, jpg = cv2.imencode(".jpg", np.full((40, 40, 3), 9, np.uint8))
    for _ in range(50):
        b.push(jpg.tobytes())
    assert b.dropped == 49
    assert b.read()[0] and not b.read()[0]
    b.push(b"not a jpeg")
    assert b.read() == (False, None)


def test_browser_frames_reach_pipeline(tmp_path):
    out = []
    w, store, made, scene = make_worker(tmp_path, [Person(0, lambda f: (320, 240))], out)
    w.handle(("start", {"source": "browser"}))
    ok, jpg = cv2.imencode(".jpg", scene.render())
    w.handle(("frame", jpg.tobytes()))
    assert w.tick()


def test_single_instance_lock(tmp_path):
    p = str(tmp_path / "w.lock")
    a = W.SingleInstance(p)
    with pytest.raises(W.WorkerAlreadyRunning):
        W.SingleInstance(p)
    del a


def test_key_file_is_private(tmp_path):
    import os
    p = str(tmp_path / "k")
    k = W.load_or_create_key(p)
    assert len(k) == 32 and oct(os.stat(p).st_mode & 0o777) == "0o600" and W.load_or_create_key(p) == k


def test_transport_authenticated_roundtrip_and_bad_key_rejected(tmp_path):
    from multiprocessing.connection import Client
    from multiprocessing import AuthenticationError
    t = W.Transport(port=0 if False else 18765, key=b"k" * 32)
    with pytest.raises((AuthenticationError, Exception)):
        Client((W.HOST, 18765), authkey=b"wrong" * 6).send(("status",))
    c = Client((W.HOST, 18765), authkey=b"k" * 32)
    c.send(("status",))
    assert t.cmds.get(timeout=2) == ("status",)
    t.send(("status", {"ok": 1}))
    assert c.recv() == ("status", {"ok": 1})
    c.close()
    time.sleep(0.2)
    assert t.cmds.get(timeout=2) == ("watch", False)       # viewer gone -> previews stop


def test_command_queue_is_bounded():
    t = W.Transport(port=18766, key=b"k" * 32)
    for i in range(200):
        t.cmds_put(("status",))
    assert t.cmds.qsize() == 64


def test_enrollment_rpc_flow_with_simulated_pad(tmp_path):
    """Enrollment runs in the worker: LIVE accepted, SPOOF refused, photos marked 'liveness not verified'."""
    from test_pad_pipeline import FakePAD
    out = []
    w, store, made, scene = make_worker(tmp_path, [Person(1, lambda f: (320, 240))], out)
    store.delete_student("R0")
    fake = FakePAD(0.95); fake.health = lambda: {"state": "READY", "reason": "", "model_id": "sim", "models": []}
    w.pad = fake
    w._pad_for_rpc = lambda: fake
    w.enroll.get_pad = lambda: fake
    w.handle(("rpc", 1, "enroll_open", ({"roll_number": "x9", "name": "Xavi"},)))
    sid = [m for m in out if m[0] == "rpc_result"][-1][2]["result"]["session_id"]
    img = scene.render()
    jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 98])[1].tobytes()
    w.handle(("rpc", 2, "enroll_sample", (sid, jpg)))
    r = [m for m in out if m[0] == "rpc_result"][-1][2]
    assert r["ok"] and r["result"]["accepted"] and r["result"]["pad_state"] == "LIVE", r
    fake.real = 0.02
    w.handle(("rpc", 3, "enroll_sample", (sid, jpg)))
    r = [m for m in out if m[0] == "rpc_result"][-1][2]["result"]
    assert not r["accepted"] and r["pad_state"] == "SPOOF" and r["count"] == 1
    fake.real = 0.95
    w.handle(("rpc", 4, "enroll_finish", (sid,)))
    r = [m for m in out if m[0] == "rpc_result"][-1][2]
    assert r["ok"] and r["result"]["liveness_verified"] is True
    assert store.list_students()[-1]["roll_number"] == "X9"
    # photos path: never "verified"
    w.handle(("rpc", 5, "enroll_photos", ({"roll_number": "X8", "name": "Yan", "filenames": ["a.jpg"]}, [jpg])))
    r = [m for m in out if m[0] == "rpc_result"][-1][2]
    assert (r["ok"] is False and "already matches" in r["error"]) or r["result"]["liveness_verified"] is False
    assert "embedding" not in str(out).lower()


def test_client_rpc_roundtrip_over_real_transport(tmp_path):
    from backend.worker_client import WorkerClient, WorkerError
    t = W.Transport(port=18767, key=b"k" * 32)
    out = []
    w, *_ = make_worker(tmp_path, [], out)
    w.send = t.send
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                w.handle(t.cmds.get(timeout=0.05))
            except Exception:
                pass
    th = threading.Thread(target=loop, daemon=True); th.start()
    c = WorkerClient(port=18767, key=b"k" * 32)
    assert c.available()
    r = c.rpc("enroll_open", {"roll_number": "a1", "name": "A"})
    assert r["target_samples"] == 5
    with pytest.raises(WorkerError):
        c.rpc("enroll_open", {"roll_number": "", "name": ""})
    c.viewer(+1); time.sleep(0.2)
    assert w.watching
    c.viewer(-1); time.sleep(0.2)
    assert not w.watching
    stop.set()
