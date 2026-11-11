"""
Golden regression: with liveness_mode="off" the pipeline must behave exactly as it did before the PAD
upgrade. tests/golden_off_mode.json was generated from the ORIGINAL pipeline.py (commit 4d76d5f plus the
unmodified recognition code) with `python tests/test_golden_off_mode.py --generate`, BEFORE any PAD hook
was added. Scripted fake detector/recogniser (same approach as test_pipeline_logic.py); no neural nets.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ATTENDANCE_DB", os.path.join(tempfile.mkdtemp(prefix="golden_"), "t.db"))

from database import Store                                           # noqa: E402
from test_pipeline_logic import Person, emb, make, run, walker       # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_off_mode.json")


def snapshot(tmp_dir, **make_over):
    store = Store(os.path.join(tmp_dir, "g.db"))
    for k, (roll, name) in enumerate([("R0", "Asha"), ("R1", "Bimal"), ("R2", "Chitra")]):
        store.add_student(roll, name, [emb(k)])
    persons = [Person(0, walker(120, 150, 2)), Person(1, walker(280, 260, 2)), Person(2, walker(440, 150, 2), score=0.8),
               Person(9, walker(200, 360, 2)), Person(0, lambda f: (500, 330), sharp=False,
                                                   active=lambda f: f > 10)]
    scene, pipe, clock = make(store, persons, **make_over)
    infos = run(scene, pipe, 70, clock=clock)
    tracks = sorted((t.id, t.ident.status, t.ident.student.roll_number if t.ident.student else None,
                     round(t.ident.similarity, 4), t.ident.attempts, t.ident.hint)
                    for t in pipe.tracker.tracks if t.ident)
    rows = [(r["roll_number"], r["direction"], round(r["similarity"], 4)) for r in
            sorted(store.all_logs(), key=lambda r: (r["roll_number"], r["timestamp"]))]
    events = [e for _, info in infos for e in info["new_events"]]
    per_frame = [(i["faces"], sorted(i["identified"]), i["unknown"]) for _, i in infos]
    return {"tracks": tracks, "rows": rows, "events": [e.split("  ", 1)[-1] for e in events],
            "per_frame": per_frame}


def test_off_mode_matches_pre_upgrade_golden(tmp_path):
    expected = json.load(open(GOLDEN))
    got = json.loads(json.dumps(snapshot(str(tmp_path))))
    assert got == expected


def test_off_mode_pipeline_has_no_pad_side_effects(tmp_path):
    store = Store(str(tmp_path / "n.db"))
    store.add_student("R0", "Asha", [emb(0)])
    scene, pipe, clock = make(store, [Person(0, lambda f: (320, 240))])
    run(scene, pipe, 25, clock=clock)
    assert len(store.all_logs()) == 1
    with store._conn() as c:
        tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
        cols = {r[1] for r in c.execute("pragma table_info(attendance_logs)")}
    assert "pad_events" not in tables and "pad_state" not in cols


if __name__ == "__main__" and "--generate" in sys.argv:
    with tempfile.TemporaryDirectory() as d:
        json.dump(json.loads(json.dumps(snapshot(d))), open(GOLDEN, "w"), indent=1)
    print("wrote", GOLDEN)
