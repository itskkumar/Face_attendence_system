"""
dashboard.py - Streamlit entry point (Module C).   Run:  streamlit run dashboard.py

Minimalistic dashboard showing data entry, known/unknown person counts, and recent activity.
Auto-refreshes every few seconds to reflect live recognition data.
"""
import datetime as dt

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from ui_common import get_store

st.set_page_config(page_title="Attendance Dashboard", page_icon="🎓", layout="wide")
st_autorefresh(interval=3000, key="dashboard_refresh")

store = get_store()
unique_today = store.today_unique_count()
known_today = store.today_known_count()
unknown_today = store.today_unknown_count()
scans_today = store.today_total_scans()
students = store.list_students()
recent = store.recent_entries(15)

# Custom CSS for minimalistic design
st.markdown("""
<style>
    /* Clean typography */
    .main-title {
        font-size: 2rem;
        font-weight: 600;
        color: #1a1a1a;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
    }
    .subtitle {
        font-size: 0.875rem;
        color: #666;
        margin-bottom: 2rem;
    }

    /* Card styling */
    .stat-card {
        background: #ffffff;
        border: 1px solid #e5e5e5;
        border-radius: 8px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }

    .stat-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #666;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }

    .stat-value {
        font-size: 2.5rem;
        font-weight: 600;
        color: #1a1a1a;
        line-height: 1;
    }

    .stat-secondary {
        font-size: 0.875rem;
        color: #999;
        margin-top: 0.5rem;
    }

    /* Section headers */
    .section-header {
        font-size: 0.875rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #333;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #e5e5e5;
    }

    /* Status badges */
    .status-known {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        background: #10b981;
        color: white;
        border-radius: 4px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    .status-unknown {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        background: #6b7280;
        color: white;
        border-radius: 4px;
        font-size: 0.875rem;
        font-weight: 500;
    }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Adjust spacing */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown(f"<div class='main-title'>Attendance Dashboard</div>", unsafe_allow_html=True)
st.markdown(f"<div class='subtitle'>Last updated: {dt.datetime.now():%b %d, %Y at %I:%M:%S %p}</div>",
            unsafe_allow_html=True)

# Main metrics row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Total Today</div>
        <div class="stat-value">{unique_today}</div>
        <div class="stat-secondary">unique visitors</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Known Persons</div>
        <div class="stat-value">{known_today}</div>
        <div class="stat-secondary">enrolled students</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Unknown Persons</div>
        <div class="stat-value">{unknown_today}</div>
        <div class="stat-secondary">not recognized</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Total Scans</div>
        <div class="stat-value">{scans_today}</div>
        <div class="stat-secondary">{len(students)} enrolled</div>
    </div>
    """, unsafe_allow_html=True)

# Two-column layout for data entry and recent activity
left_col, right_col = st.columns([1, 2])

# Left column: Quick data entry
with left_col:
    st.markdown("<div class='section-header'>Quick Entry</div>", unsafe_allow_html=True)

    with st.form("quick_entry_form", clear_on_submit=False):
        st.markdown("**Add new student**")
        entry_name = st.text_input("Full name", placeholder="John Doe", label_visibility="collapsed",
                                    key="entry_name_input")
        entry_roll = st.text_input("Roll number", placeholder="2024-CS-001", label_visibility="collapsed",
                                    key="entry_roll_input")

        st.caption("Use the Enrollment page in the sidebar for photo capture and full registration.")

        submitted = st.form_submit_button("Go to Enrollment →", use_container_width=True)
        if submitted:
            st.info("👉 Please use the **Enrollment** page in the sidebar to capture photos and complete registration.")

    st.markdown("<div class='section-header'>System Info</div>", unsafe_allow_html=True)
    st.metric("Enrolled Students", len(students))
    st.metric("Recognition Rate",
              f"{(known_today / unique_today * 100):.0f}%" if unique_today > 0 else "0%")

    st.caption("📹 Use the **Live Feed** page to start camera processing")

# Right column: Recent activity
with right_col:
    st.markdown("<div class='section-header'>Recent Activity</div>", unsafe_allow_html=True)

    if recent:
        # Create a clean dataframe with styled data
        df_display = []
        for entry in recent:
            status_badge = ("Known" if entry.get("similarity") and entry.get("similarity") > 0.4
                          else "Unknown")
            df_display.append({
                "Time": entry["timestamp"].split()[1][:5],  # HH:MM only
                "Name": entry["name"],
                "Roll Number": entry["roll_number"],
                "Status": status_badge,
                "Direction": entry["direction"]
            })

        df = pd.DataFrame(df_display)

        # Display as a clean table
        st.dataframe(
            df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Time": st.column_config.TextColumn("Time", width="small"),
                "Name": st.column_config.TextColumn("Name", width="medium"),
                "Roll Number": st.column_config.TextColumn("Roll #", width="small"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Direction": st.column_config.TextColumn("Direction", width="small"),
            }
        )
    else:
        st.info("No activity yet. Enroll students and start the Live Feed to begin tracking attendance.")

# Download section
st.markdown("<div class='section-header'>Export Data</div>", unsafe_allow_html=True)

logs = store.all_logs()
if logs:
    col_dl1, col_dl2, _ = st.columns([1, 1, 2])
    with col_dl1:
        st.download_button(
            "⬇ Download Full Log (CSV)",
            pd.DataFrame(logs).to_csv(index=False).encode("utf-8"),
            file_name=f"attendance_{dt.datetime.now():%Y%m%d_%H%M%S}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col_dl2:
        # Download today's log only
        today_logs = [log for log in logs
                     if log["timestamp"].startswith(dt.datetime.now().strftime("%Y-%m-%d"))]
        if today_logs:
            st.download_button(
                "⬇ Download Today's Log",
                pd.DataFrame(today_logs).to_csv(index=False).encode("utf-8"),
                file_name=f"attendance_today_{dt.datetime.now():%Y%m%d}.csv",
                mime="text/csv",
                use_container_width=True
            )
else:
    st.caption("No attendance data to export yet.")

# Footer note
st.divider()
st.caption("💡 **Tip:** This dashboard auto-refreshes every 3 seconds. Use the sidebar to access Live Feed and Enrollment pages.")
