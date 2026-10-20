"""
database_setup.py - create the SQLite database and tables.

    python database_setup.py            # create tables if missing (safe to re-run)
    python database_setup.py --reset    # DELETE everything and start fresh
"""
import argparse
import os

from config import DB_PATH
from database import Store, init_db


def main() -> None:
    ap = argparse.ArgumentParser(description="Initialise the attendance database")
    ap.add_argument("--reset", action="store_true", help="delete the existing database first")
    args = ap.parse_args()

    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(DB_PATH + suffix)
            except FileNotFoundError:
                pass
        print("[database_setup] existing database removed")

    init_db(DB_PATH)
    store = Store(DB_PATH)
    print(f"[database_setup] ready: {DB_PATH}")
    print(f"[database_setup] enrolled students: {len(store.list_students())}")


if __name__ == "__main__":
    main()
