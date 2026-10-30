"""
pages/4_Search.py - Advanced search and filtering for attendance logs.

Features: date range filtering, person search, camera filtering,
attendance percentage calculator, and filtered exports.
"""
import datetime as dt

import pandas as pd
import streamlit as st

from ui_common import get_store

st.set_page_config(page_title="Search & Filter", page_icon="🔍", layout="wide")
st.title("🔍 Search & Filter Attendance")

store = get_store()

# Search filters in sidebar
st.sidebar.header("Search Filters")

# Date range
col1, col2 = st.sidebar.columns(2)
start_date = col1.date_input("Start date", dt.datetime.now() - dt.timedelta(days=7))
end_date = col2.date_input("End date", dt.datetime.now())

# Person search
search_name = st.sidebar.text_input("Search by name", placeholder="e.g., John Doe")
search_roll = st.sidebar.text_input("Search by roll number", placeholder="e.g., 2024-CS-001")

# Camera filter
cameras = store.get_camera_stats()
camera_options = ["All Cameras"] + [c["camera_label"] for c in cameras]
camera_filter = st.sidebar.selectbox("Filter by camera", camera_options)

# Result limit
result_limit = st.sidebar.slider("Max results", 10, 5000, 500)

# Search button
search_clicked = st.sidebar.button("🔍 Search", type="primary", use_container_width=True)

# ============================================================================
# Main content
# ============================================================================

tab_search, tab_student = st.tabs(["Search Results", "Student Profile"])

# ============================================================================
# TAB 1: Search Results
# ============================================================================
with tab_search:
    if search_clicked or search_name or search_roll:
        with st.spinner("Searching..."):
            results = store.search_logs(
                start_date=start_date.strftime("%Y-%m-%d") if start_date else None,
                end_date=end_date.strftime("%Y-%m-%d") if end_date else None,
                roll_number=search_roll if search_roll else None,
                name=search_name if search_name else None,
                camera_label=camera_filter if camera_filter != "All Cameras" else None,
                limit=result_limit
            )

        if results:
            st.success(f"✅ Found {len(results)} matching records")

            df = pd.DataFrame(results)

            # Summary statistics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Results", len(results))
            col2.metric("Unique Persons", df["roll_number"].nunique())
            col3.metric("Known Persons", df[df["student_id"].notna()]["roll_number"].nunique())
            col4.metric("Unknown Persons", df[df["student_id"].isna()]["roll_number"].nunique())

            # Display results
            st.markdown("### Search Results")
            display_columns = ["timestamp", "name", "roll_number", "direction", "similarity", "camera_label", "source"]
            df_display = df[display_columns].copy()
            df_display["similarity"] = df_display["similarity"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")

            st.dataframe(
                df_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "timestamp": "Time",
                    "name": "Name",
                    "roll_number": "Roll Number",
                    "direction": "Direction",
                    "similarity": "Match Score",
                    "camera_label": "Camera",
                    "source": "Source"
                }
            )

            # Download filtered results
            col_dl1, col_dl2, _ = st.columns([1, 1, 2])

            with col_dl1:
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "⬇ Download Full Results (CSV)",
                    csv,
                    f"attendance_search_{dt.datetime.now():%Y%m%d_%H%M%S}.csv",
                    "text/csv",
                    use_container_width=True
                )

            with col_dl2:
                # Download summary (unique entries only)
                df_copy = df.copy()
                df_copy['date'] = df_copy['timestamp'].apply(lambda x: x[:10])
                df_unique = df_copy.drop_duplicates(subset=["roll_number", "date"])
                csv_unique = df_unique.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "⬇ Download Unique Entries (CSV)",
                    csv_unique,
                    f"attendance_unique_{dt.datetime.now():%Y%m%d_%H%M%S}.csv",
                    "text/csv",
                    use_container_width=True
                )

        else:
            st.info("No results found. Try adjusting your search filters.")
    else:
        st.info("👈 Use the filters in the sidebar to search attendance records")

# ============================================================================
# TAB 2: Student Profile & Attendance Percentage
# ============================================================================
with tab_student:
    st.subheader("Student Profile & Attendance Percentage")

    # Student selector
    students = store.list_students()
    if students:
        student_options = [f"{s['roll_number']} - {s['name']}" for s in students]
        selected_student = st.selectbox("Select student", student_options)

        if selected_student:
            roll_number = selected_student.split(" - ")[0]

            # Get profile
            profile = store.get_student_profile(roll_number)

            if profile:
                # Display profile information
                st.markdown("### Profile Information")

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"**Name:** {profile['name']}")
                    st.markdown(f"**Roll Number:** {profile['roll_number']}")
                    st.markdown(f"**Department:** {profile.get('department', 'N/A')}")
                    st.markdown(f"**Batch:** {profile.get('batch', 'N/A')}")

                with col2:
                    st.markdown(f"**Email:** {profile.get('email', 'N/A')}")
                    st.markdown(f"**Phone:** {profile.get('phone', 'N/A')}")
                    st.markdown(f"**Expected Time:** {profile.get('expected_time', 'N/A')}")
                    st.markdown(f"**Enrolled:** {profile['created_at']}")

                st.divider()

                # Attendance percentage calculator
                st.markdown("### Attendance Analysis")

                period_days = st.slider("Analysis period (days)", 7, 90, 30)

                attendance_pct = store.get_attendance_percentage(roll_number, period_days)

                # Color-coded metric
                if attendance_pct >= 75:
                    color = "🟢"
                    status = "Good"
                elif attendance_pct >= 50:
                    color = "🟡"
                    status = "Fair"
                else:
                    color = "🔴"
                    status = "Poor"

                col1, col2, col3 = st.columns(3)
                col1.metric("Attendance Rate", f"{attendance_pct:.1f}%")
                col2.metric("Status", f"{color} {status}")
                col3.metric("Total Logs", profile['total_attendance'])

                # Get detailed attendance history
                st.markdown(f"### Attendance History (Last {period_days} days)")

                history = store.search_logs(
                    start_date=(dt.datetime.now() - dt.timedelta(days=period_days)).strftime("%Y-%m-%d"),
                    end_date=dt.datetime.now().strftime("%Y-%m-%d"),
                    roll_number=roll_number,
                    limit=1000
                )

                if history:
                    df_history = pd.DataFrame(history)
                    df_history["date"] = df_history["timestamp"].apply(lambda x: x[:10])
                    df_history["time"] = df_history["timestamp"].apply(lambda x: x[11:16])

                    # Daily summary
                    daily_summary = df_history.groupby("date").agg({
                        "id": "count",
                        "time": "first"
                    }).rename(columns={"id": "entries", "time": "first_entry"})

                    st.dataframe(
                        daily_summary,
                        use_container_width=True,
                        column_config={
                            "entries": "Total Entries",
                            "first_entry": "First Entry Time"
                        }
                    )

                    # Download student history
                    csv = df_history.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        f"⬇ Download {profile['name']}'s Attendance History",
                        csv,
                        f"student_{roll_number}_{dt.datetime.now():%Y%m%d}.csv",
                        "text/csv"
                    )
                else:
                    st.info(f"No attendance records found for the last {period_days} days")
            else:
                st.error("Student profile not found")
    else:
        st.info("No students enrolled yet. Use the Enrollment page to add students.")

# Footer
st.divider()
st.caption("💡 **Tip:** Use date ranges and filters to generate custom attendance reports")
