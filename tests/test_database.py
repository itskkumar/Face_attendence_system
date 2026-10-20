import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pytest

from database import Gallery, Store


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.db"))


def vec(seed, noise=0.0, base=None):
    rng = np.random.default_rng(seed)
    v = base if base is not None else rng.normal(size=512)
    if noise:
        v = v + rng.normal(scale=noise, size=512)
    return (v / np.linalg.norm(v)).astype(np.float32)


def test_enroll_and_match_multi_template(store):
    a, b = vec(1), vec(2)
    store.add_student("r1", "Asha", [vec(1, 0.01, a), vec(10, 0.01, a)])
    store.add_student("r2", "Bimal", [b])
    g = store.load_gallery()
    assert g.size == 2
    m = g.match(vec(99, 0.01, a))
    assert m.student.roll_number == "R1" and m.similarity > 0.8 and m.margin > 0.5
    assert Gallery.accept(m, 0.45, 0.05)
    stranger = g.match(vec(500))
    assert not Gallery.accept(stranger, 0.45, 0.05)


def test_margin_rejects_ambiguous_match(store):
    base = vec(1)
    store.add_student("r1", "A", [vec(2, 0.002, base)])
    store.add_student("r2", "B", [vec(3, 0.002, base)])          # near-identical identity
    m = store.load_gallery().match(base)
    assert m.margin < 0.05 and not Gallery.accept(m, 0.45, 0.05)


def test_gallery_version_bumps_and_delete_cascades(store):
    v0 = store.gallery_version()
    store.add_student("r1", "A", [vec(1)])
    assert store.gallery_version() == v0 + 1
    assert store.delete_student("r1")
    assert store.gallery_version() == v0 + 2
    assert store.load_gallery().size == 0 and store.list_students() == []


def test_replace_vs_append_and_template_cap(store):
    store.add_student("r1", "A", [vec(1), vec(2)])
    assert store.list_students()[0]["templates"] == 2
    store.add_student("r1", "A", [vec(3)], mode="append")
    assert store.list_students()[0]["templates"] == 3
    store.add_student("r1", "A", [vec(4)], mode="replace")
    assert store.list_students()[0]["templates"] == 1
    store.add_student("r1", "A", [vec(i) for i in range(30)], mode="append")
    assert store.list_students()[0]["templates"] == 20


def test_duplicate_identity_detection(store):
    a = vec(1)
    store.add_student("r1", "Asha", [a])
    assert store.find_duplicate_identity([vec(7, 0.01, a)], "r2")[0] == "R1"
    assert store.find_duplicate_identity([vec(7, 0.01, a)], "r1") is None   # same person re-enrolling is fine
    assert store.find_duplicate_identity([vec(500)], "r2") is None


def test_cooldown_blocks_second_log_and_expires(store):
    store.add_student("r1", "A", [vec(1)])
    t0 = datetime(2026, 1, 5, 9, 0, 0)
    assert store.log_attendance("R1", "A", 1, 0.7, "ENTRY", "t", 300, now=t0)[0]
    assert not store.log_attendance("R1", "A", 1, 0.7, "ENTRY", "t", 300, now=t0 + timedelta(seconds=299))[0]
    assert store.log_attendance("R1", "A", 1, 0.7, "ENTRY", "t", 300, now=t0 + timedelta(seconds=301))[0]
    assert store.today_total_scans(now=t0) == 2 and store.today_unique_count(now=t0) == 1


def test_cooldown_is_atomic_under_concurrency(store):
    store.add_student("r1", "A", [vec(1)])
    now = datetime.now()
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda _: store.log_attendance("R1", "A", 1, 0.7, "ENTRY", "t", 300, now=now)[0],
                              range(40)))
    assert sum(results) == 1                                       # exactly one writer wins


def test_today_counts_ignore_yesterday_and_hourly_buckets(store):
    store.add_student("r1", "A", [vec(1)]); store.add_student("r2", "B", [vec(2)])
    day = datetime(2026, 3, 10, 12, 0, 0)
    store.log_attendance("R1", "A", 1, .7, "ENTRY", "t", 300, now=day - timedelta(days=1))
    store.log_attendance("R1", "A", 1, .7, "ENTRY", "t", 300, now=day.replace(hour=9, minute=5))
    store.log_attendance("R2", "B", 2, .7, "ENTRY", "t", 300, now=day.replace(hour=9, minute=40))
    store.log_attendance("R2", "B", 2, .7, "ENTRY", "t", 300, now=day.replace(hour=11, minute=0))
    assert store.today_unique_count(now=day) == 2
    assert store.hourly_counts_today(now=day) == [("09:00", 2), ("11:00", 1)]


def test_last_seen_hydration_survives_restart(store):
    store.add_student("r1", "A", [vec(1)])
    now = datetime(2026, 1, 5, 9, 0, 0)
    store.log_attendance("R1", "A", 1, .7, "ENTRY", "t", 300, now=now)
    seen = store.last_seen_since(300, now=now + timedelta(seconds=100))
    assert "R1" in seen
    assert store.last_seen_since(300, now=now + timedelta(seconds=400)) == {}
