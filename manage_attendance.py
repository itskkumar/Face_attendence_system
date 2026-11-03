"""
manage_attendance.py - Manage attendance logs and their snapshots.

Usage:
    python manage_attendance.py --stats                           # Show attendance statistics
    python manage_attendance.py --list-recent 10                  # Show recent 10 logs
    python manage_attendance.py --delete-log 17                   # Delete specific log by ID
    python manage_attendance.py --delete-student ROLL123          # Delete all logs for a student
    python manage_attendance.py --delete-date 2026-10-30          # Delete all logs from a date
    python manage_attendance.py --delete-older-than 30            # Delete logs older than 30 days
    python manage_attendance.py --delete-all                      # Delete all attendance logs
    python manage_attendance.py --dry-run --delete-all            # Preview without deleting
"""
import argparse
import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Tuple

from config import DATA_DIR, DB_PATH


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def delete_snapshot_file(snapshot_path: str) -> bool:
    """Delete a snapshot file given its relative path."""
    if not snapshot_path:
        return False

    full_path = os.path.join(DATA_DIR, snapshot_path)
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            return True
        except Exception as e:
            print(f"  ⚠️  Failed to delete {snapshot_path}: {e}")
            return False
    return False


def delete_logs_with_snapshots(log_ids: List[int], dry_run: bool = False) -> Tuple[int, int]:
    """
    Delete attendance logs and their associated snapshots.

    Returns:
        (logs_deleted, snapshots_deleted)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get snapshot paths for these logs
    placeholders = ','.join('?' * len(log_ids))
    cursor.execute(
        f"SELECT id, face_snapshot, person_snapshot FROM attendance_logs WHERE id IN ({placeholders})",
        log_ids
    )

    logs = cursor.fetchall()
    snapshots_to_delete = []

    for log in logs:
        if log['face_snapshot']:
            snapshots_to_delete.append(log['face_snapshot'])
        if log['person_snapshot']:
            snapshots_to_delete.append(log['person_snapshot'])

    if dry_run:
        print(f"[DRY RUN] Would delete {len(logs)} attendance log(s)")
        print(f"[DRY RUN] Would delete {len(snapshots_to_delete)} snapshot file(s)")
        conn.close()
        return len(logs), len(snapshots_to_delete)

    # Delete snapshot files
    snapshots_deleted = 0
    for snapshot_path in snapshots_to_delete:
        if delete_snapshot_file(snapshot_path):
            snapshots_deleted += 1

    # Delete logs from database
    cursor.execute(f"DELETE FROM attendance_logs WHERE id IN ({placeholders})", log_ids)
    logs_deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return logs_deleted, snapshots_deleted


def show_stats():
    """Show attendance log statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Total logs
    cursor.execute("SELECT COUNT(*) FROM attendance_logs")
    total_logs = cursor.fetchone()[0]

    # Logs with snapshots
    cursor.execute("SELECT COUNT(*) FROM attendance_logs WHERE face_snapshot IS NOT NULL")
    with_snapshots = cursor.fetchone()[0]

    # Date range
    cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM attendance_logs")
    date_range = cursor.fetchone()

    # Unique students
    cursor.execute("SELECT COUNT(DISTINCT roll_number) FROM attendance_logs")
    unique_students = cursor.fetchone()[0]

    # By date
    cursor.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as count
        FROM attendance_logs
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
        LIMIT 10
    """)
    by_date = cursor.fetchall()

    conn.close()

    print("📊 Attendance Log Statistics:")
    print(f"  Total logs: {total_logs}")
    print(f"  Logs with snapshots: {with_snapshots}")
    print(f"  Unique students: {unique_students}")
    if date_range[0]:
        print(f"  Date range: {date_range[0]} to {date_range[1]}")

    print(f"\n  Recent dates:")
    for row in by_date:
        print(f"    {row['date']}: {row['count']} logs")


def list_recent_logs(limit: int = 10):
    """List recent attendance logs."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, roll_number, name, timestamp, direction, similarity,
               CASE WHEN face_snapshot IS NOT NULL THEN 'Yes' ELSE 'No' END as has_snapshot
        FROM attendance_logs
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    logs = cursor.fetchall()
    conn.close()

    if not logs:
        print("No attendance logs found.")
        return

    print(f"\n📋 Recent {len(logs)} Attendance Logs:")
    print(f"{'ID':<6} {'Roll':<12} {'Name':<20} {'Timestamp':<20} {'Dir':<6} {'Sim':<6} {'Snap':<5}")
    print("-" * 85)

    for log in logs:
        print(f"{log['id']:<6} {log['roll_number']:<12} {log['name']:<20} "
              f"{log['timestamp']:<20} {log['direction']:<6} "
              f"{log['similarity']:<6.2f} {log['has_snapshot']:<5}")


def delete_log_by_id(log_id: int, dry_run: bool = False):
    """Delete a specific attendance log by ID."""
    logs_deleted, snapshots_deleted = delete_logs_with_snapshots([log_id], dry_run)

    if dry_run:
        return

    if logs_deleted > 0:
        print(f"✓ Deleted attendance log ID {log_id}")
        print(f"✓ Deleted {snapshots_deleted} snapshot(s)")
    else:
        print(f"❌ Log ID {log_id} not found")


def delete_logs_by_student(roll_number: str, dry_run: bool = False):
    """Delete all logs for a specific student."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all log IDs for this student
    cursor.execute("SELECT id FROM attendance_logs WHERE roll_number = ?", (roll_number.upper(),))
    log_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()

    if not log_ids:
        print(f"No logs found for student: {roll_number}")
        return

    logs_deleted, snapshots_deleted = delete_logs_with_snapshots(log_ids, dry_run)

    if dry_run:
        print(f"[DRY RUN] Found {len(log_ids)} log(s) for student {roll_number}")
        return

    print(f"✓ Deleted {logs_deleted} log(s) for student {roll_number}")
    print(f"✓ Deleted {snapshots_deleted} snapshot(s)")


def delete_logs_by_date(date_str: str, dry_run: bool = False):
    """Delete all logs from a specific date."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all log IDs for this date
    cursor.execute(
        "SELECT id FROM attendance_logs WHERE DATE(timestamp) = ?",
        (date_str,)
    )
    log_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()

    if not log_ids:
        print(f"No logs found for date: {date_str}")
        return

    logs_deleted, snapshots_deleted = delete_logs_with_snapshots(log_ids, dry_run)

    if dry_run:
        print(f"[DRY RUN] Found {len(log_ids)} log(s) for date {date_str}")
        return

    print(f"✓ Deleted {logs_deleted} log(s) from {date_str}")
    print(f"✓ Deleted {snapshots_deleted} snapshot(s)")


def delete_logs_older_than(days: int, dry_run: bool = False):
    """Delete logs older than N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all log IDs older than cutoff
    cursor.execute(
        "SELECT id FROM attendance_logs WHERE timestamp < ?",
        (cutoff,)
    )
    log_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()

    if not log_ids:
        print(f"No logs found older than {days} days")
        return

    logs_deleted, snapshots_deleted = delete_logs_with_snapshots(log_ids, dry_run)

    if dry_run:
        print(f"[DRY RUN] Found {len(log_ids)} log(s) older than {days} days")
        return

    print(f"✓ Deleted {logs_deleted} log(s) older than {days} days")
    print(f"✓ Deleted {snapshots_deleted} snapshot(s)")


def delete_all_logs(dry_run: bool = False):
    """Delete all attendance logs."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all log IDs
    cursor.execute("SELECT id FROM attendance_logs")
    log_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()

    if not log_ids:
        print("No logs to delete")
        return

    logs_deleted, snapshots_deleted = delete_logs_with_snapshots(log_ids, dry_run)

    if dry_run:
        print(f"[DRY RUN] Would delete all {len(log_ids)} attendance log(s)")
        return

    print(f"✓ Deleted all {logs_deleted} attendance log(s)")
    print(f"✓ Deleted {snapshots_deleted} snapshot(s)")


def main():
    parser = argparse.ArgumentParser(description="Manage attendance logs and snapshots")
    parser.add_argument("--stats", action="store_true", help="Show attendance statistics")
    parser.add_argument("--list-recent", type=int, metavar="N", help="List recent N logs")
    parser.add_argument("--delete-log", type=int, metavar="ID", help="Delete specific log by ID")
    parser.add_argument("--delete-student", metavar="ROLL", help="Delete all logs for a student")
    parser.add_argument("--delete-date", metavar="YYYY-MM-DD", help="Delete all logs from a date")
    parser.add_argument("--delete-older-than", type=int, metavar="DAYS", help="Delete logs older than N days")
    parser.add_argument("--delete-all", action="store_true", help="Delete all attendance logs")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    if args.list_recent:
        list_recent_logs(args.list_recent)
        return

    # Confirmation for destructive operations
    if not args.dry_run:
        if args.delete_all:
            confirm = input("⚠️  Delete ALL attendance logs and snapshots? Type 'yes' to confirm: ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return
        elif args.delete_student or args.delete_date or args.delete_older_than:
            confirm = input("⚠️  This will delete logs and their snapshots. Type 'yes' to confirm: ")
            if confirm.lower() != 'yes':
                print("Cancelled.")
                return

    if args.delete_log:
        delete_log_by_id(args.delete_log, args.dry_run)
    elif args.delete_student:
        delete_logs_by_student(args.delete_student, args.dry_run)
    elif args.delete_date:
        delete_logs_by_date(args.delete_date, args.dry_run)
    elif args.delete_older_than:
        delete_logs_older_than(args.delete_older_than, args.dry_run)
    elif args.delete_all:
        delete_all_logs(args.dry_run)
    else:
        parser.print_help()
        print("\n💡 Tip: Use --stats to see attendance statistics")
        print("💡 Tip: Use --list-recent 10 to see recent logs")


if __name__ == "__main__":
    main()
