"""
PAD gate behaviour inside the real GatePipeline. SIMULATED: a scripted fake PAD provider replaces
MiniFASNet (and the usual fake detector/recogniser replaces SCRFD/ArcFace). These tests prove the GATING
LOGIC, not the accuracy of any model.
"""
import sqlite3
import time

import numpy as np
import pytest

import antispoof as A
from test_pipeline_logic import Person, emb, env, make, run, walker   # noqa: F401  (env is a fixture)


class FakePAD(A.PADProvider):
    """SIMULATED provider: returns whatever `real` / `state` say."""
    model_id = "simulated"

    def __init__(self, real=0.95, state=None):
        self.real, self.state, self.calls = real, state, 0

    def observe(self, frame_bgr, bbox_xyxy):
        self.calls += 1
        if self.state in (A.NOT_CONFIGURED, A.ERROR):
            return A.PADResult(self.state, model_id=self.model_id, reason="simulated")
        st = A.LIVE if self.real >= 0.7 else A.SPOOF if self.real <= 0.3 else A.UNCERTAIN
        return A.PADResult(st, self.real, 1 - self.real, self.model_id, 1.0)

    def health(self):
        return {"state": "READY", "reason": "", "model_id": self.model_id, "models": []}


def pad_make(store, persons, pad, policy="reject", **over):
    events = []
    over.setdefault("liveness_mode", "minifas")
    over["pad_unconfigured_policy"] = policy
    over.setdefault("pad_edge_margin_px", 0)
    scene, pipe, clock = make(store, persons, **over)
    pipe.pad = pad
    pipe.event_sink = events.append
    return scene, pipe, clock, events


def pad_events(store):
    c = sqlite3.connect(store.path)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("select * from pad_events order by id")]
    finally:
        c.close()


def rows(store):
    c = sqlite3.connect(store.path)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("select * from attendance_logs")]
    finally:
        c.close()


def types(events):
    return [e["type"] for e in events]


def test_live_passes_and_is_logged_with_pad_columns(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(0.95))
    run(scene, pipe, 30, clock=clock)
    r = rows(env)
    assert len(r) == 1 and r[0]["roll_number"] == "R0" and r[0]["pad_state"] == A.LIVE and r[0]["pad_score"] > 0.9
    t = types(ev)
    assert "liveness.started" in t and "liveness.passed" in t and "identity.verified" in t and "attendance.recorded" in t
    assert t.index("liveness.passed") < t.index("attendance.recorded")
    assert all("embedding" not in str(e).lower() for e in ev)


def test_spoof_blocks_attendance_and_is_flagged(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(0.03))
    run(scene, pipe, 40, clock=clock)
    assert rows(env) == []
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.status == "spoof" and pipe.ui_status(tr) == "POSSIBLE SPOOF"
    flagged = [e for e in pad_events(env) if e["flagged"]]
    assert flagged and flagged[0]["state"] == A.SPOOF
    assert "liveness.failed" in types(ev) and "attendance.recorded" not in types(ev)


def test_uncertain_blocks_attendance_and_asks_for_review(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(0.5),
                                      pad_max_observation_seconds=0.0)
    run(scene, pipe, 40, clock=clock)
    time.sleep(0.01)
    run(scene, pipe, 20, start=40, clock=clock)
    assert rows(env) == []
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.status == "identified" and tr.ident.pad_state == A.UNCERTAIN    # name may show, attendance may not
    assert pipe.ui_status(tr) == "REVIEW REQUIRED"
    assert "liveness.uncertain" in types(ev)


def test_too_few_observations_is_never_live(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(0.99), pad_min_obs=50)
    run(scene, pipe, 40, clock=clock)
    assert rows(env) == []


@pytest.mark.parametrize("policy,expected", [("reject", "attendance.rejected"), ("manual_review", "review.required")])
def test_not_configured_follows_policy_and_never_logs(env, policy, expected):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], A.NullPAD(), policy=policy)
    run(scene, pipe, 30, clock=clock)
    assert rows(env) == []
    assert expected in types(ev)
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert pipe.ui_status(tr) == "PAD NOT CONFIGURED"


def test_provider_error_never_logs(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(state=A.ERROR))
    run(scene, pipe, 30, clock=clock)
    assert rows(env) == []


def test_face_at_frame_edge_gives_no_observation(env):
    pad = FakePAD(0.99)
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (55, 240))], pad, pad_edge_margin_px=10)
    run(scene, pipe, 30, clock=clock)
    assert pad.calls == 0 and rows(env) == []


def _deferred_scene(env, pad, mode):
    """Person visible for a few frames (pending: min_votes high), then leaves; deferred worker may identify."""
    persons = [Person(0, lambda f: (320, 240), active=lambda f: f < 6)]
    over = dict(min_votes=3, early_accept_sim=2.0, deferred_min_embeddings=2, track_max_age=4,
                enable_deferred_recognition=True, liveness_mode=mode, pad_min_obs=3)
    if mode == "minifas":
        scene, pipe, clock, ev = pad_make(env, persons, pad, **over)
    else:
        scene, pipe, clock = make(env, persons, **over)
    run(scene, pipe, 40, clock=clock)
    deadline = time.time() + 3
    while time.time() < deadline and not pipe._deferred_queue.empty():
        time.sleep(0.02)
    time.sleep(0.3)
    pipe.close()
    return pipe


def test_deferred_path_logs_in_off_mode_control(env):
    _deferred_scene(env, None, "off")
    assert len(rows(env)) == 1                      # proves the scenario really exercises the deferred path


def test_deferred_path_blocked_without_live(env):
    pipe = _deferred_scene(env, FakePAD(0.5), "minifas")
    assert rows(env) == []


def test_deferred_path_blocked_when_pad_not_configured(env):
    _deferred_scene(env, A.NullPAD(), "minifas")
    assert rows(env) == []


def test_reverify_revokes_on_spoof_keeps_saved_row_and_audits(env):
    pad = FakePAD(0.95)
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], pad, reverify_interval_frames=3)
    run(scene, pipe, 25, clock=clock)
    assert len(rows(env)) == 1
    pad.real = 0.02                                   # the face is now a replay
    run(scene, pipe, 60, start=25, clock=clock)
    tr = [t for t in pipe.tracker.tracks if t.confirmed][0]
    assert tr.ident.status == "spoof"
    assert len(rows(env)) == 1                        # saved row is NOT deleted
    assert any(e["flagged"] and "after identification" in e["note"] for e in pad_events(env))
    assert any(a["action"] == "pad_spoof_after_identification" for a in env.get_audit_logs())
    assert any(e["type"] == "liveness.failed" and e.get("after_identification") for e in ev)


def test_no_attendance_row_without_live_in_any_state(env):
    for real, state in [(0.95, None), (0.5, None), (0.02, None), (0.0, A.NOT_CONFIGURED), (0.0, A.ERROR)]:
        c = sqlite3.connect(env.path); c.execute("delete from attendance_logs"); c.commit(); c.close()
        scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240)), Person(1, lambda f: (150, 240))],
                                          FakePAD(real, state))
        run(scene, pipe, 40, clock=clock)
        for r in rows(env):
            assert r["pad_state"] == A.LIVE, (real, state, r)
        if real < 0.7 or state:
            assert rows(env) == []
        pipe.close()


def test_ui_status_values_and_track_details_have_no_embeddings(env):
    scene, pipe, clock, ev = pad_make(env, [Person(0, lambda f: (320, 240))], FakePAD(0.95))
    infos = run(scene, pipe, 30, clock=clock)
    d = infos[-1][1]["tracks"][0]
    assert d["status"] == "ATTENDANCE RECORDED" and d["pad_state"] == A.LIVE and d["name"] == "Asha"
    assert set(d) == {"track_id", "bbox", "status", "name", "roll_number", "det_score", "similarity",
                      "pad_state", "pad_real_prob", "hint"}
