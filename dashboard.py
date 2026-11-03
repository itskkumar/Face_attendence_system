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
from auth import check_authentication, get_current_user

st.set_page_config(page_title="Attendance Dashboard", page_icon="🎓", layout="wide")

# Check authentication
role = check_authentication()
if not role:
    st.warning("🔒 Please log in to access the dashboard")
    if st.button("Go to Login Page", type="primary"):
        st.switch_page("pages/0_🔐_Login.py")
    st.stop()

st_autorefresh(interval=3000, key="dashboard_refresh")

store = get_store()

# Role-based data fetching
if role == "student":
    username = get_current_user()
    # Student username is their roll number
    with store._conn() as c:
        student_data = c.execute("SELECT * FROM students WHERE roll_number = ?", (username,)).fetchone()
        if not student_data:
            st.error("❌ Student record not found")
            st.stop()

        # Get student-specific stats
        today_str = dt.datetime.now().strftime("%Y-%m-%d")
        student_logs = c.execute(
            "SELECT * FROM attendance_logs WHERE roll_number = ? AND timestamp LIKE ? ORDER BY timestamp DESC LIMIT 15",
            (username, f"{today_str}%")
        ).fetchall()
        recent = [dict(row) for row in student_logs]

        # Stats for student
        unique_today = len(student_logs)
        known_today = len(student_logs)
        unknown_today = 0
        scans_today = len(student_logs)
        students = [dict(student_data)]
else:
    # Admin sees everything
    unique_today = store.today_unique_count()
    known_today = store.today_known_count()
    unknown_today = store.today_unknown_count()
    scans_today = store.today_total_scans()
    students = store.list_students()
    recent = store.recent_entries(15)

# Glass morphism CSS with animations
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    * {
        font-family: 'Inter', sans-serif;
    }

    /* Animated gradient background */
    .stApp {
        background: linear-gradient(-45deg, #667eea 0%, #764ba2 25%, #f093fb 50%, #4facfe 100%);
        background-size: 400% 400%;
        animation: gradientShift 15s ease infinite;
    }

    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    /* Glass morphism cards */
    .stat-card {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: all 0.3s ease;
        animation: fadeInUp 0.6s ease-out;
    }

    .stat-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 12px 40px 0 rgba(31, 38, 135, 0.5);
        background: rgba(255, 255, 255, 0.15);
    }

    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .stat-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgba(255, 255, 255, 0.8);
        font-weight: 500;
        margin-bottom: 0.5rem;
    }

    .stat-value {
        font-size: 2.5rem;
        font-weight: 700;
        color: white;
        line-height: 1;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        animation: countUp 0.8s ease-out;
    }

    @keyframes countUp {
        from {
            opacity: 0;
            transform: scale(0.5);
        }
        to {
            opacity: 1;
            transform: scale(1);
        }
    }

    .stat-secondary {
        font-size: 0.875rem;
        color: rgba(255, 255, 255, 0.7);
        margin-top: 0.5rem;
    }

    /* Main title */
    .main-title {
        font-size: 2.5rem;
        font-weight: 700;
        color: white;
        margin-bottom: 0.5rem;
        letter-spacing: -0.02em;
        text-shadow: 0 2px 10px rgba(0,0,0,0.2);
        animation: slideDown 0.6s ease-out;
    }

    @keyframes slideDown {
        from {
            opacity: 0;
            transform: translateY(-20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    .subtitle {
        font-size: 0.875rem;
        color: rgba(255, 255, 255, 0.8);
        margin-bottom: 2rem;
    }

    /* Section headers */
    .section-header {
        font-size: 1rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: white;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid rgba(255, 255, 255, 0.2);
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* Glass morphism container */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* Dataframe styling */
    .stDataFrame {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        overflow: hidden;
    }

    /* Form styling */
    .stForm {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 1.5rem;
    }

    /* Input fields */
    .stTextInput > div > div > input {
        background: rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 10px;
        color: white;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
        background: rgba(255, 255, 255, 0.3);
        border: 1px solid rgba(255, 255, 255, 0.5);
        box-shadow: 0 0 20px rgba(255, 255, 255, 0.3);
    }

    .stTextInput > label {
        color: white !important;
        font-weight: 500;
    }

    /* Button styling */
    .stButton > button {
        background: rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 10px;
        color: white;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        background: rgba(255, 255, 255, 0.3);
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
    }

    /* Download button */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stDownloadButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
    }

    /* Metric styling */
    .stMetric {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 10px;
        padding: 1rem;
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    .stMetric label {
        color: rgba(255, 255, 255, 0.8) !important;
    }

    .stMetric [data-testid="stMetricValue"] {
        color: white !important;
        font-weight: 700;
    }

    /* Info/Caption text */
    .stCaption {
        color: rgba(255, 255, 255, 0.7) !important;
    }

    /* Alert boxes */
    .stAlert {
        background: rgba(255, 255, 255, 0.15);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 12px;
        color: white;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-right: 1px solid rgba(255, 255, 255, 0.2);
    }

    [data-testid="stSidebar"] * {
        color: white !important;
    }

    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Divider */
    hr {
        border-color: rgba(255, 255, 255, 0.2);
    }
</style>
""", unsafe_allow_html=True)

# Header
user = get_current_user()
st.markdown(f"<div class='main-title'>👤 {user}'s Attendance</div>" if role == "student" else "<div class='main-title'>Attendance Dashboard</div>", unsafe_allow_html=True)
st.markdown(f"<div class='subtitle'>Last updated: {dt.datetime.now():%b %d, %Y at %I:%M:%S %p} | Role: {role.upper()}</div>",
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
if role == "admin":
    left_col, right_col = st.columns([1, 2])

    # Left column: Quick data entry (Admin only)
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
else:
    # Student view - full width for activity
    right_col = st.container()

    # Show student info
    st.markdown("<div class='section-header'>Your Profile</div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Your Roll Number", username)
    with col2:
        st.metric("Total Check-ins Today", unique_today)
    with col3:
        st.metric("Enrolled", "✅ Yes" if students else "❌ No")

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

# Download section (Admin only)
if role == "admin":
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
else:
    # Students can download their own attendance
    st.markdown("<div class='section-header'>Export Your Data</div>", unsafe_allow_html=True)
    if recent:
        # Get all student logs, not just today
        with store._conn() as c:
            all_student_logs = c.execute(
                "SELECT * FROM attendance_logs WHERE roll_number = ? ORDER BY timestamp DESC",
                (username,)
            ).fetchall()
            student_logs_data = [dict(row) for row in all_student_logs]

        st.download_button(
            "⬇ Download My Attendance History (CSV)",
            pd.DataFrame(student_logs_data).to_csv(index=False).encode("utf-8"),
            file_name=f"my_attendance_{username}_{dt.datetime.now():%Y%m%d}.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.caption("No attendance records to export yet.")

# Footer note
st.divider()
st.caption("💡 **Tip:** This dashboard auto-refreshes every 3 seconds. Use the sidebar to access Live Feed and Enrollment pages.")
