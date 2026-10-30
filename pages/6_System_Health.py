"""
pages/6_System_Health.py - System health monitoring and reliability features.

Features: health metrics dashboard, database backup, audit logs,
performance monitoring, and system diagnostics.
"""
import datetime as dt
import os
import shutil
import sqlite3

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config import DB_PATH, DATA_DIR
from ui_common import get_store

st.set_page_config(page_title="System Health", page_icon="🏥", layout="wide")
st.title("🏥 System Health & Monitoring")

# Auto-refresh every 10 seconds
st_autorefresh(interval=10000, key="health_refresh")

store = get_store()

# Tabs for different monitoring functions
tab_dashboard, tab_backup, tab_audit, tab_diagnostics = st.tabs([
    "Dashboard", "Backup & Recovery", "Audit Logs", "Diagnostics"
])

# ============================================================================
# TAB 1: Health Dashboard
# ============================================================================
with tab_dashboard:
    st.subheader("System Health Dashboard")

    # Get current system stats
    col1, col2, col3, col4 = st.columns(4)

    # Database size
    db_size_mb = os.path.getsize(DB_PATH) / (1024 * 1024) if os.path.exists(DB_PATH) else 0
    col1.metric("Database Size", f"{db_size_mb:.2f} MB")

    # Total students
    students = store.list_students()
    col2.metric("Enrolled Students", len(students))

    # Total logs
    total_logs = store.today_total_scans()
    col3.metric("Logs Today", total_logs)

    # Gallery version
    gallery_version = store.gallery_version()
    col4.metric("Gallery Version", gallery_version)

    st.divider()

    # System uptime and recent activity
    st.markdown("### Recent Activity")

    # Get recent logs for activity monitoring
    recent = store.recent_entries(100)
    if recent:
        df_recent = pd.DataFrame(recent)

        # Activity chart - entries per minute over last 100 logs
        df_recent['minute'] = df_recent['timestamp'].apply(lambda x: x[:16])  # YYYY-MM-DD HH:MM
        activity_by_minute = df_recent.groupby('minute').size()

        st.line_chart(activity_by_minute, use_container_width=True)

        # Activity stats
        col1, col2, col3 = st.columns(3)

        unique_persons = df_recent['roll_number'].nunique()
        known_persons = df_recent[df_recent['similarity'].notna()]['roll_number'].nunique()
        avg_similarity = df_recent[df_recent['similarity'].notna()]['similarity'].mean()

        col1.metric("Unique Persons (last 100)", unique_persons)
        col2.metric("Known Persons", known_persons)
        col3.metric("Avg Recognition Score", f"{avg_similarity:.2f}" if pd.notna(avg_similarity) else "N/A")
    else:
        st.info("No recent activity to display")

    st.divider()

    # Health metrics logging
    st.markdown("### Health Metrics")

    # Log current health metrics
    if st.button("📊 Record Current Metrics"):
        store.log_health_metric("database_size_mb", db_size_mb)
        store.log_health_metric("total_students", len(students))
        store.log_health_metric("gallery_version", gallery_version)
        st.success("✅ Metrics recorded")

    # Display health trends (last 24 hours)
    col1, col2 = st.columns(2)

    with col1:
        db_metrics = store.get_health_metrics("database_size_mb", 24)
        if db_metrics:
            df_db = pd.DataFrame(db_metrics, columns=["Timestamp", "Size (MB)"])
            st.line_chart(df_db.set_index("Timestamp"), use_container_width=True)
            st.caption("Database Size Trend (24h)")

    with col2:
        student_metrics = store.get_health_metrics("total_students", 24)
        if student_metrics:
            df_students = pd.DataFrame(student_metrics, columns=["Timestamp", "Count"])
            st.line_chart(df_students.set_index("Timestamp"), use_container_width=True)
            st.caption("Student Count Trend (24h)")

# ============================================================================
# TAB 2: Backup & Recovery
# ============================================================================
with tab_backup:
    st.subheader("Database Backup & Recovery")

    # Backup directory
    backup_dir = os.path.join(DATA_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    st.markdown(f"**Backup Location:** `{backup_dir}`")

    # Create backup
    st.markdown("### Create Backup")

    if st.button("💾 Create Backup Now", type="primary", use_container_width=True):
        try:
            timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"attendance_backup_{timestamp}.db")

            # Create backup using SQLite backup API
            source = sqlite3.connect(DB_PATH)
            dest = sqlite3.connect(backup_path)

            with dest:
                source.backup(dest)

            source.close()
            dest.close()

            backup_size_mb = os.path.getsize(backup_path) / (1024 * 1024)

            st.success(f"✅ Backup created successfully!")
            st.info(f"**File:** `{os.path.basename(backup_path)}`  \n**Size:** {backup_size_mb:.2f} MB")

            # Log audit
            store.log_audit("system", "create_backup", f"Created backup: {os.path.basename(backup_path)}")

        except Exception as e:
            st.error(f"❌ Backup failed: {str(e)}")

    st.divider()

    # List existing backups
    st.markdown("### Existing Backups")

    if os.path.exists(backup_dir):
        backup_files = [f for f in os.listdir(backup_dir) if f.endswith('.db')]
        backup_files.sort(reverse=True)  # Most recent first

        if backup_files:
            backup_data = []
            for filename in backup_files:
                filepath = os.path.join(backup_dir, filename)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                modified = dt.datetime.fromtimestamp(os.path.getmtime(filepath))
                backup_data.append({
                    'filename': filename,
                    'size_mb': f"{size_mb:.2f}",
                    'created': modified.strftime("%Y-%m-%d %H:%M:%S"),
                    'age_hours': (dt.datetime.now() - modified).total_seconds() / 3600
                })

            df_backups = pd.DataFrame(backup_data)

            st.dataframe(
                df_backups[['filename', 'size_mb', 'created']],
                hide_index=True,
                use_container_width=True,
                column_config={
                    'filename': 'Backup File',
                    'size_mb': 'Size (MB)',
                    'created': 'Created At'
                }
            )

            # Backup cleanup
            st.markdown("### Backup Management")

            col1, col2 = st.columns(2)

            with col1:
                # Auto-cleanup old backups
                max_backups = st.number_input("Keep last N backups", min_value=1, max_value=100, value=10)
                if st.button("🧹 Cleanup Old Backups"):
                    if len(backup_files) > max_backups:
                        to_delete = backup_files[max_backups:]
                        for filename in to_delete:
                            os.remove(os.path.join(backup_dir, filename))
                        st.success(f"✅ Deleted {len(to_delete)} old backups")
                        st.rerun()
                    else:
                        st.info(f"No cleanup needed. Only {len(backup_files)} backups exist.")

            with col2:
                # Download backup
                selected_backup = st.selectbox("Download backup", [""] + backup_files)
                if selected_backup:
                    backup_path = os.path.join(backup_dir, selected_backup)
                    with open(backup_path, 'rb') as f:
                        st.download_button(
                            "⬇ Download Backup File",
                            f,
                            selected_backup,
                            "application/x-sqlite3",
                            use_container_width=True
                        )

        else:
            st.info("No backups found. Create your first backup above.")
    else:
        st.info("Backup directory not found. It will be created when you make your first backup.")

    st.divider()

    # Restore warning
    st.markdown("### Restore Database")
    st.warning("⚠️ **Warning:** Restoring a backup will replace all current data. This cannot be undone!")
    st.caption("To restore a backup, stop the application and manually replace the database file.")

# ============================================================================
# TAB 3: Audit Logs
# ============================================================================
with tab_audit:
    st.subheader("Audit Trail")

    # Get audit logs
    audit_logs = store.get_audit_logs(limit=200)

    if audit_logs:
        df_audit = pd.DataFrame(audit_logs)

        st.markdown(f"**Showing last {len(audit_logs)} audit entries**")

        # Filter by action
        actions = ['All'] + sorted(df_audit['action'].unique().tolist())
        selected_action = st.selectbox("Filter by action", actions)

        if selected_action != 'All':
            df_audit = df_audit[df_audit['action'] == selected_action]

        # Display audit logs
        st.dataframe(
            df_audit[['timestamp', 'user', 'action', 'details']],
            hide_index=True,
            use_container_width=True,
            column_config={
                'timestamp': 'Time',
                'user': 'User',
                'action': 'Action',
                'details': 'Details'
            }
        )

        # Export audit logs
        csv = df_audit.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇ Download Audit Log (CSV)",
            csv,
            f"audit_log_{dt.datetime.now():%Y%m%d_%H%M%S}.csv",
            "text/csv"
        )

    else:
        st.info("No audit logs recorded yet")

    st.divider()

    # Manual audit log entry
    st.markdown("### Record Manual Entry")
    with st.form("manual_audit"):
        audit_user = st.text_input("User", value="admin")
        audit_action = st.text_input("Action")
        audit_details = st.text_area("Details")

        if st.form_submit_button("📝 Log Entry"):
            if audit_action:
                store.log_audit(audit_user, audit_action, audit_details)
                st.success("✅ Audit entry recorded")
                st.rerun()
            else:
                st.error("Action is required")

# ============================================================================
# TAB 4: System Diagnostics
# ============================================================================
with tab_diagnostics:
    st.subheader("System Diagnostics")

    # Database diagnostics
    st.markdown("### Database Diagnostics")

    if st.button("🔍 Run Database Check"):
        with st.spinner("Checking database integrity..."):
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()

                # Run integrity check
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()

                if result[0] == "ok":
                    st.success("✅ Database integrity check passed")
                else:
                    st.warning(f"⚠️ Database issues detected: {result[0]}")

                # Get table info
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = cursor.fetchall()

                st.markdown("**Tables in database:**")
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                    count = cursor.fetchone()[0]
                    st.text(f"• {table[0]}: {count} rows")

                conn.close()

            except Exception as e:
                st.error(f"❌ Diagnostic failed: {str(e)}")

    st.divider()

    # Performance metrics
    st.markdown("### Performance Metrics")

    col1, col2 = st.columns(2)

    with col1:
        # Gallery load test
        if st.button("⚡ Test Gallery Load Speed"):
            import time
            start = time.time()
            gallery = store.load_gallery()
            elapsed = time.time() - start

            st.metric("Gallery Load Time", f"{elapsed*1000:.2f} ms")
            st.metric("Gallery Size", f"{gallery.size} students")
            st.metric("Total Templates", gallery.matrix.shape[0])

    with col2:
        # Database query test
        if st.button("⚡ Test Query Performance"):
            import time

            # Test various queries
            queries = {
                "Recent logs": "SELECT * FROM attendance_logs ORDER BY id DESC LIMIT 100",
                "Student list": "SELECT * FROM students",
                "Today's count": f"SELECT COUNT(DISTINCT roll_number) FROM attendance_logs WHERE timestamp >= '{store._today_start()}'"
            }

            results = {}
            for name, query in queries.items():
                start = time.time()
                with store._conn() as c:
                    c.execute(query).fetchall()
                elapsed = time.time() - start
                results[name] = elapsed * 1000

            st.markdown("**Query Performance:**")
            for name, ms in results.items():
                st.text(f"• {name}: {ms:.2f} ms")

    st.divider()

    # System information
    st.markdown("### System Information")

    info_col1, info_col2 = st.columns(2)

    with info_col1:
        st.markdown(f"**Database Path:** `{DB_PATH}`")
        st.markdown(f"**Data Directory:** `{DATA_DIR}`")
        st.markdown(f"**Database Exists:** {'✅ Yes' if os.path.exists(DB_PATH) else '❌ No'}")

    with info_col2:
        st.markdown(f"**Current Time:** {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
        st.markdown(f"**Gallery Version:** {gallery_version}")
        st.markdown(f"**Max Templates/Student:** 20")

# Footer
st.divider()
st.caption("🔄 Dashboard auto-refreshes every 10 seconds")
