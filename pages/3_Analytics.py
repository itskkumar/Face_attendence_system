"""
pages/3_Analytics.py - Comprehensive attendance analytics and reports.

Features: attendance trends, peak hours, absence tracking, late arrivals,
camera statistics, and downloadable reports.
"""
import datetime as dt

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from ui_common import get_store

st.set_page_config(page_title="Analytics & Reports", page_icon="📊", layout="wide")
st.title("📊 Analytics & Reports")

# Auto-refresh every 30 seconds
st_autorefresh(interval=30000, key="analytics_refresh")

store = get_store()

# Date range selector
st.sidebar.header("Report Settings")
days_range = st.sidebar.slider("Analysis period (days)", 1, 90, 30)
late_hour = st.sidebar.slider("Late arrival threshold (hour)", 6, 12, 9)

# Tabs for different analytics
tab_trends, tab_peaks, tab_absences, tab_late, tab_cameras = st.tabs([
    "Trends", "Peak Hours", "Absences", "Late Arrivals", "Cameras"
])

# ============================================================================
# TAB 1: Attendance Trends
# ============================================================================
with tab_trends:
    st.subheader(f"Attendance Trends - Last {days_range} Days")

    trends = store.get_attendance_trends(days_range)

    if trends:
        df_trends = pd.DataFrame(trends, columns=["Date", "Unique Persons", "Total Scans"])

        # Line chart for trends
        st.line_chart(df_trends.set_index("Date"))

        # Summary statistics
        col1, col2, col3, col4 = st.columns(4)

        avg_unique = df_trends["Unique Persons"].mean()
        max_unique = df_trends["Unique Persons"].max()
        min_unique = df_trends["Unique Persons"].min()
        total_days = len(df_trends)

        col1.metric("Average Daily Attendance", f"{avg_unique:.1f}")
        col2.metric("Peak Day", f"{max_unique}")
        col3.metric("Lowest Day", f"{min_unique}")
        col4.metric("Days with Data", total_days)

        # Detailed table
        st.markdown("### Daily Breakdown")
        st.dataframe(df_trends, hide_index=True, use_container_width=True)

        # Download button
        csv = df_trends.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇ Download Trends Report (CSV)",
            csv,
            f"attendance_trends_{dt.datetime.now():%Y%m%d}.csv",
            "text/csv",
            use_container_width=True
        )
    else:
        st.info("No attendance data available for the selected period.")

# ============================================================================
# TAB 2: Peak Hours Analysis
# ============================================================================
with tab_peaks:
    st.subheader(f"Peak Hours Analysis - Last {days_range} Days")

    peak_hours = store.get_peak_hours(days_range)

    if peak_hours:
        df_peaks = pd.DataFrame(peak_hours, columns=["Hour", "Count"])
        df_peaks["Hour"] = df_peaks["Hour"].apply(lambda x: f"{x:02d}:00")

        # Bar chart
        st.bar_chart(df_peaks.set_index("Hour"))

        # Top 3 peak hours
        st.markdown("### Busiest Hours")
        col1, col2, col3 = st.columns(3)

        top_3 = sorted(peak_hours, key=lambda x: x[1], reverse=True)[:3]
        if len(top_3) >= 1:
            col1.metric("1st Peak", f"{top_3[0][0]:02d}:00", f"{top_3[0][1]} entries")
        if len(top_3) >= 2:
            col2.metric("2nd Peak", f"{top_3[1][0]:02d}:00", f"{top_3[1][1]} entries")
        if len(top_3) >= 3:
            col3.metric("3rd Peak", f"{top_3[2][0]:02d}:00", f"{top_3[2][1]} entries")

        # Detailed table
        st.dataframe(df_peaks, hide_index=True)
    else:
        st.info("No attendance data available for peak hours analysis.")

# ============================================================================
# TAB 3: Absence Tracking
# ============================================================================
with tab_absences:
    st.subheader(f"Students Absent - Last {days_range} Days")

    absent = store.get_absent_students(days_range)

    if absent:
        df_absent = pd.DataFrame(absent)

        st.warning(f"⚠️ {len(absent)} students have not attended in the last {days_range} days")

        st.dataframe(
            df_absent,
            hide_index=True,
            use_container_width=True,
            column_config={
                "roll_number": "Roll Number",
                "name": "Name",
                "department": "Department",
                "batch": "Batch"
            }
        )

        # Download absent students list
        csv = df_absent.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇ Download Absent Students List (CSV)",
            csv,
            f"absent_students_{dt.datetime.now():%Y%m%d}.csv",
            "text/csv"
        )
    else:
        st.success(f"✅ All enrolled students have attended in the last {days_range} days!")

# ============================================================================
# TAB 4: Late Arrivals
# ============================================================================
with tab_late:
    st.subheader(f"Late Arrivals (after {late_hour}:00)")

    # Date selector for late arrivals
    selected_date = st.date_input("Select date", dt.datetime.now()).strftime("%Y-%m-%d")

    late_arrivals = store.get_late_arrivals(selected_date, late_hour)

    if late_arrivals:
        df_late = pd.DataFrame(late_arrivals)

        st.warning(f"⏰ {len(late_arrivals)} late arrivals on {selected_date}")

        st.dataframe(
            df_late[["roll_number", "name", "timestamp"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "roll_number": "Roll Number",
                "name": "Name",
                "timestamp": "Arrival Time"
            }
        )

        # Download late arrivals
        csv = df_late.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇ Download Late Arrivals (CSV)",
            csv,
            f"late_arrivals_{selected_date}.csv",
            "text/csv"
        )
    else:
        st.success(f"✅ No late arrivals on {selected_date} (threshold: {late_hour}:00)")

# ============================================================================
# TAB 5: Camera Statistics
# ============================================================================
with tab_cameras:
    st.subheader("Multi-Camera Statistics")

    camera_stats = store.get_camera_stats()

    if camera_stats:
        df_cameras = pd.DataFrame(camera_stats)

        st.markdown("### Activity by Camera")
        st.dataframe(
            df_cameras,
            hide_index=True,
            use_container_width=True,
            column_config={
                "camera_label": "Camera",
                "total": "Total Entries",
                "unique_persons": "Unique Persons"
            }
        )

        # Pie chart for camera distribution
        st.markdown("### Distribution")
        st.bar_chart(df_cameras.set_index("camera_label")["total"])
    else:
        st.info("No camera data available yet.")

# Footer
st.divider()
st.caption(f"📅 Report generated on {dt.datetime.now():%B %d, %Y at %I:%M %p}")
