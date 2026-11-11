import os
import shutil
import sqlite3

import pytest

import pad_store

SHIPPED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "attendance_system.db")


def _dump(path):
    c = sqlite3.connect(path)
    try:
        out = {}
        for (t,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
            if t == "pad_events":
                continue
            cols = [r[1] for r in c.execute(f"pragma table_info({t})") if r[1] not in ("pad_state", "pad_score")]
            out[t] = c.execute(f"select {','.join(cols)} from {t} order by 1").fetchall()
        return out
    finally:
        c.close()


@pytest.mark.skipif(not os.path.exists(SHIPPED), reason="shipped data/attendance_system.db not present")
def test_migration_on_copy_of_shipped_db_keeps_every_row_and_is_idempotent(tmp_path):
    db = tmp_path / "data" / "attendance_system.db"
    db.parent.mkdir()
    shutil.copy(SHIPPED, db)
    before = _dump(str(db))
    backup = pad_store.migrate_pad_schema(str(db))
    pad_store.migrate_pad_schema(str(db))                    # second run must be a no-op
    assert backup and os.path.exists(backup)
    assert _dump(str(db)) == before                           # all existing rows and columns intact
    c = sqlite3.connect(str(db))
    cols = {r[1] for r in c.execute("pragma table_info(attendance_logs)")}
    assert {"pad_state", "pad_score"} <= cols
    assert c.execute("select count(*) from pad_events").fetchone()[0] == 0
    assert c.execute("select count(*) from attendance_logs where pad_state is not null").fetchone()[0] == 0
    c.close()
    assert sqlite3.connect(backup).execute("select count(*) from attendance_logs").fetchone()[0] == len(before["attendance_logs"])
