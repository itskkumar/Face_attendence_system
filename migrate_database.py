"""
migrate_database.py - Database migration script for new features.

Run this once to add new columns and tables to your existing database.
"""
import sqlite3
import os
from config import DB_PATH

def migrate_database():
    """Add new columns and tables to existing database."""
    print(f"Migrating database at: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("Database doesn't exist yet - will be created with new schema automatically.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Add new columns to students table (if they don't exist)
        print("\n1. Updating students table...")
        new_student_columns = [
            ("email", "TEXT"),
            ("phone", "TEXT"),
            ("department", "TEXT"),
            ("batch", "TEXT"),
            ("expected_time", "TEXT")
        ]

        for col_name, col_type in new_student_columns:
            try:
                cursor.execute(f"ALTER TABLE students ADD COLUMN {col_name} {col_type}")
                print(f"   ✓ Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print(f"   - Column {col_name} already exists")
                else:
                    raise

        # Add camera_label column to attendance_logs table
        print("\n2. Updating attendance_logs table...")
        try:
            cursor.execute("ALTER TABLE attendance_logs ADD COLUMN camera_label TEXT DEFAULT 'default'")
            print("   ✓ Added column: camera_label")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("   - Column camera_label already exists")
            else:
                raise

        # Create index on camera_label
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_camera ON attendance_logs(camera_label)")
            print("   ✓ Created index: idx_logs_camera")
        except sqlite3.OperationalError:
            print("   - Index idx_logs_camera already exists")

        # Create new tables
        print("\n3. Creating new tables...")

        # Audit logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                user        TEXT NOT NULL,
                action      TEXT NOT NULL,
                details     TEXT,
                ip_address  TEXT
            )
        """)
        print("   ✓ Created table: audit_logs")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(timestamp)")
        print("   ✓ Created index: idx_audit_ts")

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role        TEXT NOT NULL DEFAULT 'viewer',
                created_at  TEXT NOT NULL
            )
        """)
        print("   ✓ Created table: users")

        # System health table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_health (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                metric      TEXT NOT NULL,
                value       REAL NOT NULL
            )
        """)
        print("   ✓ Created table: system_health")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_health_ts ON system_health(timestamp)")
        print("   ✓ Created index: idx_health_ts")

        conn.commit()
        print("\n✅ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
