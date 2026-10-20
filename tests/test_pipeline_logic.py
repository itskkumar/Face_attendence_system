"""
End-to-end pipeline logic with a scripted fake detector/recogniser.

Each synthetic "person" is a coloured, noisy rectangle. FakeEngine returns a box + landmarks for
every active person and identifies a crop by its centre colour, so the whole real pipeline (tracking,
alignment, blur/pose gates, voting, cooldown, DB logging, drawing) runs exactly as in production -
only the neural networks are replaced.
"""
import dataclasses
import cv2
from datetime import datetime, timedelta

import numpy as np
import pytest

from attendance import AttendanceLogger
from config import DEFAULT_SETTINGS
from database import Store
from pipeline import GatePipeline
from tracker import Detection

W, H = 640, 480
COLORS = {0: (200, 60, 60), 1: (60, 200, 60), 2: (60, 60, 200), 3: (200, 200, 60), 9: (60, 200, 200)}


def emb(k):
    v = np.random.default_rng(1000 + k).normal(size=512)
    return (v / np.linalg.norm(v)).astype(np.float32)


class Person:
    def __init__(self, pid, traj, sharp=True, active=lambda f: True, score=0.9):
        self.pid, self.traj, self.sharp, self.active, self.score = pid, traj, sharp, active, score
        self.override_pid = None       # simulate what the recogniser "sees" (for ID-swap test)


class Scene:
    def __init__(self, persons, seed=0):
        self.persons, self.f, self.rng = persons, 0, np.random.default_rng(seed)

    def box(self, p, w=110, h=140):
        cx, cy = p.traj(self.f)
        return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], float)

    def render(self):
        img = np.full((H, W, 3), 110, np.uint8)
        for p in self.persons:
            if not p.active(self.f):
                continue
            x1, y1, x2, y2 = [int(v) for v in self.box(p)]
            base = np.array(COLORS[p.override_pid if p.override_pid is not None else p.pid], int)
            region = np.tile(base, (y2 - y1, x2 - x1, 1))
            if p.sharp:
                region = region + self.rng.integers(-60, 60, region.shape)
            img[y1:y2, x1:x2] = np.clip(region, 0, 255).astype(np.uint8)
            if not p.sharp:                                  # genuine motion/defocus blur over the face
                a, b, c, d = max(0, y1 - 60), min(H, y2 + 60), max(0, x1 - 60), min(W, x2 + 60)
                img[a:b, c:d] = cv2.GaussianBlur(img[a:b, c:d], (0, 0), 9)
        return img


class FakeEngine:
    provider_label = "fake"

    def __init__(self, scene):
        self.scene = scene

    def detect(self, frame):
        out = []
        for p in self.scene.persons:
            if not p.active(self.scene.f):
                continue
            b = self.scene.box(p)
            w, h = b[2] - b[0], b[3] - b[1]
            kps = np.array([[b[0] + .3 * w, b[1] + .38 * h], [b[0] + .7 * w, b[1] + .38 * h],
                            [b[0] + .5 * w, b[1] + .55 * h], [b[0] + .35 * w, b[1] + .75 * h],
                            [b[0] + .65 * w, b[1] + .75 * h]])
            out.append(Detection(b, kps, p.score))
        return out

    def embed_aligned(self, crop):
        centre = crop[46:66, 46:66].reshape(-1, 3).mean(0)
        pid = min(COLORS, key=lambda k: np.linalg.norm(centre - np.array(COLORS[k])))
        e = emb(pid) + np.random.default_rng(int(centre.sum())).normal(scale=0.003, size=512)
        return (e / np.linalg.norm(e)).astype(np.float32)


class Clock:
    def __init__(self):
        self.t = datetime(2026, 2, 2, 9, 0, 0)

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    store = Store(str(tmp_path / "p.db"))
    for k, (roll, name) in enumerate([("R0", "Asha"), ("R1", "Bimal"), ("R2", "Chitra")]):
        store.add_student(roll, name, [emb(k)])
    return store


def make(store, persons, **over):
    scene = Scene(persons)
    params = dict(file_detect_every_n=1, rec_interval_frames=1, reverify_interval_frames=10_000)
    params.update(over)
    s = dataclasses.replace(DEFAULT_SETTINGS, **params)
    clock = Clock()
    logger = AttendanceLogger(store, s.cooldown_seconds, source="test", clock=clock)
    pipe = GatePipeline(FakeEngine(scene), store, s, is_file=True, logger=logger)
    return scene, pipe, clock


def run(scene, pipe, frames, start=0, clock=None, tick=0.04):
    infos = []
    for f in range(start, start + frames):
        scene.f = f
        if clock:
            clock.t += timedelta(seconds=tick)
        out, info = pipe.process(scene.render())
        infos.append((out, info))
    return infos


def walker(x0, y, vx=3):
    return lambda f: (x0 + vx * f, y)


def test_group_of_four_three_known_one_unknown(env):
    persons = [Person(0, walker(120, 150)), Person(1, walker(280, 260)), Person(2, walker(440, 150)),
               Person(9, walker(200, 380))]                       # colour 9 is not enrolled
    scene, pipe, clock = make(env, persons)
    infos = run(scene, pipe, 45, clock=clock)
    logs = env.all_logs()
    assert sorted(r["roll_number"] for r in logs) == ["R0", "R1", "R2"]      # each exactly once
    assert env.today_unique_count(now=clock.t) == 3
    last = infos[-1][1]
    assert sorted(last["identified"]) == ["Asha", "Bimal", "Chitra"]
    assert last["unknown"] == 1 and last["faces"] == 4
    assert all(r["roll_number"] != "R9" for r in logs)                       # unknown never logged


def test_cooldown_blocks_relogging_then_allows_after_window(env):
    scene, pipe, clock = make(env, [Person(0, lambda f: (320, 240))])
    run(scene, pipe, 20, clock=clock)
    assert len(env.all_logs()) == 1
    clock.t += timedelta(seconds=200)                                         # still inside 5 minutes
    run(scene, pipe, 20, start=20, clock=clock)
    assert len(env.all_logs()) == 1
    clock.t += timedelta(seconds=200)                                         # now > 300 s since first log
    run(scene, pipe, 20, start=40, clock=clock)
    assert len(env.all_logs()) == 2


def test_blurry_face_is_never_recognised_or_logged(env):
    scene, pipe, clock = make(env, [Person(0, lambda f: (320, 240), sharp=False)])
    infos = run(scene, pipe, 40, clock=clock)
    assert env.all_logs() == []
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.status == "pending" and tr.ident.hint == "blurry"


def test_small_face_is_gated(env):
    scene, pipe, clock = make(env, [Person(0, lambda f: (320, 240))], min_face_px=200)
    run(scene, pipe, 30, clock=clock)
    assert env.all_logs() == []
    assert [t for t in pipe.tracker.tracks if t.confirmed][0].ident.hint == "too small"


def test_unknown_face_turns_red_after_max_attempts_and_is_not_logged(env):
    scene, pipe, clock = make(env, [Person(9, lambda f: (320, 240))])
    run(scene, pipe, 30, clock=clock)
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.status == "unknown" and env.all_logs() == []


def test_identity_swap_is_caught_by_reverification(env):
    p = Person(0, lambda f: (320, 240))
    scene, pipe, clock = make(env, [p], reverify_interval_frames=8)
    run(scene, pipe, 15, clock=clock)
    assert [r["roll_number"] for r in env.all_logs()] == ["R0"]
    p.override_pid = 1                      # same track now shows someone else (a tracker ID swap)
    clock.t += timedelta(seconds=400)       # beyond cooldown so a correct re-log is visible
    run(scene, pipe, 60, start=15, clock=clock)
    rolls = [r["roll_number"] for r in env.all_logs()]
    assert rolls.count("R1") == 1           # the new person was identified and logged as THEMSELVES
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.student.roll_number == "R1"


def test_gate_line_direction_and_crossing_requirement(env):
    down = Person(0, lambda f: (320, 120 + 6 * f))                   # moves down across y = 0.55*480
    scene, pipe, clock = make(env, [down], gate_line_enabled=True, require_gate_crossing=True)
    run(scene, pipe, 20, clock=clock)                                # still above the line (y<=240)
    assert env.all_logs() == []                                      # recognised but waiting for the crossing
    run(scene, pipe, 25, start=20, clock=clock)
    logs = env.all_logs()
    assert len(logs) == 1 and logs[0]["direction"] == "ENTRY"

    up = Person(1, lambda f: (320, 400 - 6 * f))
    scene2, pipe2, clock2 = make(env, [up], gate_line_enabled=True, require_gate_crossing=True)
    run(scene2, pipe2, 45, clock=clock2)
    assert [r["direction"] for r in env.all_logs() if r["roll_number"] == "R1"] == ["EXIT"]


def test_new_enrolment_is_picked_up_without_restart(env):
    scene, pipe, clock = make(env, [Person(3, lambda f: (320, 240))],
                              unknown_retry_frames=15)
    run(scene, pipe, 25, clock=clock)
    assert env.all_logs() == []
    env.add_student("R3", "Dev", [emb(3)])                           # enrolled while running
    pipe._gallery_checked = 0                                        # skip the 2-second poll wait
    run(scene, pipe, 40, start=25, clock=clock)
    assert [r["roll_number"] for r in env.all_logs()] == ["R3"]


def test_detect_every_n_skips_detector_but_boxes_keep_moving(env):
    scene = Scene([Person(0, walker(100, 240, vx=4))])
    s = dataclasses.replace(DEFAULT_SETTINGS, detect_every_n=3, rec_interval_frames=1)
    pipe = GatePipeline(FakeEngine(scene), env, s, source_label="t")
    calls = {"n": 0}
    orig = pipe.engine.detect
    pipe.engine.detect = lambda fr: (calls.__setitem__("n", calls["n"] + 1), orig(fr))[1]
    xs = []
    for f in range(30):
        scene.f = f
        _, info = pipe.process(scene.render())
        vis = [t for t in pipe.tracker.tracks if t.confirmed and t.time_since_update <= pipe.display_stale]
        if vis:
            xs.append(vis[0].center[0])
    assert calls["n"] == 10                                           # detector ran on 1/3 of frames
    assert all(b > a for a, b in zip(xs, xs[1:]))                     # box advanced EVERY frame (no flicker)


def test_draw_handles_empty_scene_and_returns_same_size(env):
    scene, pipe, _ = make(env, [])
    out, info = pipe.process(scene.render())
    assert out.shape == (H, W, 3) and info["faces"] == 0
