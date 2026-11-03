"""
cleanup_snapshots.py - Manage and clean up attendance snapshots.

Usage:
    python cleanup_snapshots.py --all                    # Delete all snapshots
    python cleanup_snapshots.py --older-than 30          # Delete snapshots older than 30 days
    python cleanup_snapshots.py --date 2026-10-30        # Delete snapshots from specific date
    python cleanup_snapshots.py --dry-run --all          # Preview what would be deleted
    python cleanup_snapshots.py --orphaned               # Delete snapshots not in database
"""
import argparse
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from config import DATA_DIR, DB_PATH

SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")


def get_all_snapshot_paths_from_db():
    """Get all snapshot paths referenced in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    paths = set()
    cursor.execute("SELECT face_snapshot, person_snapshot FROM attendance_logs WHERE face_snapshot IS NOT NULL OR person_snapshot IS NOT NULL")
    for row in cursor.fetchall():
        if row[0]:  # face_snapshot
            paths.add(os.path.join(DATA_DIR, row[0]))
        if row[1]:  # person_snapshot
            paths.add(os.path.join(DATA_DIR, row[1]))

    conn.close()
    return paths


def get_all_snapshot_files():
    """Get all snapshot files on disk."""
    files = []
    if not os.path.exists(SNAPSHOTS_DIR):
        return files

    for root, dirs, filenames in os.walk(SNAPSHOTS_DIR):
        for filename in filenames:
            if filename.endswith('.jpg'):
                files.append(os.path.join(root, filename))
    return files


def delete_all_snapshots(dry_run=False):
    """Delete all snapshot files and clear database references."""
    if not os.path.exists(SNAPSHOTS_DIR):
        print("No snapshots directory found.")
        return 0

    files = get_all_snapshot_files()
    count = len(files)

    if dry_run:
        print(f"[DRY RUN] Would delete {count} snapshot files")
        for f in files[:10]:  # Show first 10
            print(f"  - {os.path.relpath(f, DATA_DIR)}")
        if count > 10:
            print(f"  ... and {count - 10} more")

        print(f"\n[DRY RUN] Would clear snapshot columns in database")
        return count

    # Delete files
    print(f"Deleting {count} snapshot files...")
    shutil.rmtree(SNAPSHOTS_DIR)
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

    # Clear database references
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE attendance_logs SET face_snapshot = NULL, person_snapshot = NULL WHERE face_snapshot IS NOT NULL OR person_snapshot IS NOT NULL")
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"✓ Deleted {count} files")
    print(f"✓ Cleared {affected} database references")
    return count


def delete_by_date(date_str, dry_run=False):
    """Delete snapshots from a specific date."""
    date_dir = os.path.join(SNAPSHOTS_DIR, date_str)

    if not os.path.exists(date_dir):
        print(f"No snapshots found for date: {date_str}")
        return 0

    files = [f for f in Path(date_dir).glob("*.jpg")]
    count = len(files)

    if dry_run:
        print(f"[DRY RUN] Would delete {count} snapshot files from {date_str}")
        for f in files[:10]:
            print(f"  - {f.name}")
        if count > 10:
            print(f"  ... and {count - 10} more")
        return count

    print(f"Deleting {count} snapshots from {date_str}...")
    shutil.rmtree(date_dir)

    # Clear database references for this date
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE attendance_logs SET face_snapshot = NULL, person_snapshot = NULL "
        "WHERE face_snapshot LIKE ? OR person_snapshot LIKE ?",
        (f"snapshots/{date_str}%", f"snapshots/{date_str}%")
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"✓ Deleted {count} files")
    print(f"✓ Cleared {affected} database references")
    return count


def delete_older_than(days, dry_run=False):
    """Delete snapshots older than N days."""
    cutoff_date = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    if not os.path.exists(SNAPSHOTS_DIR):
        print("No snapshots directory found.")
        return 0

    deleted = 0
    date_dirs = [d for d in os.listdir(SNAPSHOTS_DIR) if os.path.isdir(os.path.join(SNAPSHOTS_DIR, d))]

    for date_dir in date_dirs:
        if date_dir < cutoff_str:
            dir_path = os.path.join(SNAPSHOTS_DIR, date_dir)
            files = list(Path(dir_path).glob("*.jpg"))

            if dry_run:
                print(f"[DRY RUN] Would delete {len(files)} files from {date_dir}")
                deleted += len(files)
            else:
                print(f"Deleting {len(files)} files from {date_dir}...")
                shutil.rmtree(dir_path)
                deleted += len(files)

    if not dry_run and deleted > 0:
        # Clear database references
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE attendance_logs SET face_snapshot = NULL, person_snapshot = NULL "
            "WHERE (face_snapshot < ? OR person_snapshot < ?)",
            (f"snapshots/{cutoff_str}", f"snapshots/{cutoff_str}")
        )
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        print(f"✓ Deleted {deleted} files")
        print(f"✓ Cleared {affected} database references")
    elif dry_run:
        print(f"\n[DRY RUN] Total: {deleted} files would be deleted")

    return deleted


def delete_orphaned(dry_run=False):
    """Delete snapshot files that are not referenced in the database."""
    db_paths = get_all_snapshot_paths_from_db()
    disk_files = get_all_snapshot_files()

    orphaned = [f for f in disk_files if f not in db_paths]
    count = len(orphaned)

    if count == 0:
        print("No orphaned snapshots found.")
        return 0

    if dry_run:
        print(f"[DRY RUN] Would delete {count} orphaned snapshot files")
        for f in orphaned[:10]:
            print(f"  - {os.path.relpath(f, DATA_DIR)}")
        if count > 10:
            print(f"  ... and {count - 10} more")
        return count

    print(f"Deleting {count} orphaned snapshot files...")
    for file_path in orphaned:
        os.remove(file_path)

    # Clean up empty directories
    for root, dirs, files in os.walk(SNAPSHOTS_DIR, topdown=False):
        for dir_name in dirs:
            dir_path = os.path.join(root, dir_name)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)

    print(f"✓ Deleted {count} orphaned files")
    return count


def show_stats():
    """Show snapshot statistics."""
    if not os.path.exists(SNAPSHOTS_DIR):
        print("No snapshots directory found.")
        return

    files = get_all_snapshot_files()
    total_size = sum(os.path.getsize(f) for f in files)

    # Count by date
    by_date = {}
    for f in files:
        date = os.path.basename(os.path.dirname(f))
        by_date[date] = by_date.get(date, 0) + 1

    # Database stats
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM attendance_logs WHERE face_snapshot IS NOT NULL")
    db_count = cursor.fetchone()[0]
    conn.close()

    print(f"📊 Snapshot Statistics:")
    print(f"  Total files: {len(files)}")
    print(f"  Total size: {total_size / (1024*1024):.2f} MB")
    print(f"  Database references: {db_count}")
    print(f"  Dates with snapshots: {len(by_date)}")
    print(f"\n  By date:")
    for date in sorted(by_date.keys(), reverse=True)[:10]:
        print(f"    {date}: {by_date[date]} files")


def main():
    parser = argparse.ArgumentParser(description="Manage attendance snapshots")
    parser.add_argument("--all", action="store_true", help="Delete all snapshots")
    parser.add_argument("--date", help="Delete snapshots from specific date (YYYY-MM-DD)")
    parser.add_argument("--older-than", type=int, metavar="DAYS", help="Delete snapshots older than N days")
    parser.add_argument("--orphaned", action="store_true", help="Delete orphaned files not in database")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--stats", action="store_true", help="Show snapshot statistics")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if not any([args.all, args.date, args.older_than, args.orphaned]):
        parser.print_help()
        print("\n💡 Tip: Use --stats to see current snapshot statistics")
        return

    # Confirmation for destructive operations
    if not args.dry_run:
        if args.all:
            confirm = input("⚠️  Delete ALL snapshots? This cannot be undone. Type 'yes' to confirm: ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return

    if args.all:
        delete_all_snapshots(args.dry_run)
    elif args.date:
        delete_by_date(args.date, args.dry_run)
    elif args.older_than:
        delete_older_than(args.older_than, args.dry_run)
    elif args.orphaned:
        delete_orphaned(args.dry_run)


if __name__ == "__main__":
    main()
