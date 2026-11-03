"""
Student attendance view page with glass morphism design
"""
import datetime as dt
import pandas as pd
import streamlit as st
from auth import check_authentication, get_current_user
from ui_common import get_store

st.set_page_config(page_title="My Attendance", page_icon="📊", layout="wide")

# Check authentication - only students can access this
role = check_authentication()
if not role:
    st.warning("🔒 Please log in to view your attendance")
    if st.button("Go to Login Page", type="primary"):
        st.switch_page("pages/0_🔐_Login.py")
    st.stop()

if role != "student":
    st.error("⚠️ This page is only accessible to students")
    st.stop()

store = get_store()
username = get_current_user()

# Glass morphism CSS
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
    }

    .stat-secondary {
        font-size: 0.875rem;
        color: rgba(255, 255, 255, 0.7);
        margin-top: 0.5rem;
    }

    h1, h2, h3 {
        color: white !important;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* Dataframe styling */
    .stDataFrame {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    /* Metric styling */
    .stMetric {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
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

    /* Button styling */
    .stDownloadButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 12px;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stDownloadButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
    }

    /* Caption text */
    .stCaption {
        color: rgba(255, 255, 255, 0.7) !important;
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

    /* Hide streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# Get student info
with store._conn() as c:
    student_data = c.execute("SELECT * FROM students WHERE roll_number = ?", (username,)).fetchone()

    if not student_data:
        st.error("❌ Student record not found")
        st.stop()

    # Get all attendance logs for this student
    all_logs = c.execute(
        "SELECT * FROM attendance_logs WHERE roll_number = ? ORDER BY timestamp DESC",
        (username,)
    ).fetchall()

    # Today's logs
    today_str = dt.datetime.now().strftime("%Y-%m-%d")
    today_logs = c.execute(
        "SELECT * FROM attendance_logs WHERE roll_number = ? AND timestamp LIKE ? ORDER BY timestamp DESC",
        (username, f"{today_str}%")
    ).fetchall()

    # This week's logs
    week_ago = (dt.datetime.now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    week_logs = c.execute(
        "SELECT * FROM attendance_logs WHERE roll_number = ? AND timestamp >= ? ORDER BY timestamp DESC",
        (username, week_ago)
    ).fetchall()

    # This month's logs
    month_ago = (dt.datetime.now() - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    month_logs = c.execute(
        "SELECT * FROM attendance_logs WHERE roll_number = ? AND timestamp >= ? ORDER BY timestamp DESC",
        (username, month_ago)
    ).fetchall()

# Header
st.title(f"📊 My Attendance Record")
st.caption(f"Roll Number: {username} | Name: {student_data['name']}")

# Statistics cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Today</div>
        <div class="stat-value">{len(today_logs)}</div>
        <div class="stat-secondary">check-ins</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">This Week</div>
        <div class="stat-value">{len(week_logs)}</div>
        <div class="stat-secondary">check-ins</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">This Month</div>
        <div class="stat-value">{len(month_logs)}</div>
        <div class="stat-secondary">check-ins</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="stat-card">
        <div class="stat-label">Total</div>
        <div class="stat-value">{len(all_logs)}</div>
        <div class="stat-secondary">all time</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Filter options
st.subheader("📅 Filter Attendance")
filter_option = st.selectbox(
    "Select time period",
    ["Today", "This Week", "This Month", "All Time"]
)

# Get filtered data
if filter_option == "Today":
    filtered_logs = today_logs
elif filter_option == "This Week":
    filtered_logs = week_logs
elif filter_option == "This Month":
    filtered_logs = month_logs
else:
    filtered_logs = all_logs

# Display attendance table
st.subheader(f"📋 Attendance Records ({filter_option})")

if filtered_logs:
    df_data = []
    for log in filtered_logs:
        df_data.append({
            "Date": log["timestamp"][:10],
            "Time": log["timestamp"][11:19],
            "Direction": log["direction"],
            "Similarity": f"{log['similarity']:.2%}" if log['similarity'] else "N/A",
            "Camera": log["camera_label"] or "default"
        })

    df = pd.DataFrame(df_data)

    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Date": st.column_config.TextColumn("Date", width="medium"),
            "Time": st.column_config.TextColumn("Time", width="medium"),
            "Direction": st.column_config.TextColumn("Direction", width="small"),
            "Similarity": st.column_config.TextColumn("Confidence", width="small"),
            "Camera": st.column_config.TextColumn("Camera", width="small"),
        }
    )

    # Download button
    st.download_button(
        "⬇ Download My Attendance (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"my_attendance_{username}_{dt.datetime.now():%Y%m%d}.csv",
        mime="text/csv",
        use_container_width=True
    )
else:
    st.info(f"No attendance records found for {filter_option.lower()}.")

# Attendance calendar view
st.markdown("---")
st.subheader("📆 Monthly Calendar View")

# Get unique dates for current month
current_month = dt.datetime.now().strftime("%Y-%m")
with store._conn() as c:
    month_dates = c.execute(
        """SELECT DATE(timestamp) as date, COUNT(*) as count
           FROM attendance_logs
           WHERE roll_number = ? AND timestamp LIKE ?
           GROUP BY DATE(timestamp)
           ORDER BY date DESC""",
        (username, f"{current_month}%")
    ).fetchall()

if month_dates:
    date_counts = {row["date"]: row["count"] for row in month_dates}

    # Create a simple calendar display
    cal_data = []
    for date_str, count in date_counts.items():
        cal_data.append({
            "Date": date_str,
            "Check-ins": count,
            "Status": "✅ Present"
        })

    cal_df = pd.DataFrame(cal_data)
    st.dataframe(
        cal_df,
        hide_index=True,
        use_container_width=True
    )
else:
    st.info("No attendance records for this month yet.")

# Student profile info
st.markdown("---")
st.subheader("👤 My Profile")

col1, col2 = st.columns(2)
with col1:
    st.metric("Name", student_data["name"])
    st.metric("Roll Number", student_data["roll_number"])
    st.metric("Department", student_data["department"] or "Not Set")
with col2:
    st.metric("Batch", student_data["batch"] or "Not Set")
    st.metric("Email", student_data["email"] or "Not Set")
    st.metric("Phone", student_data["phone"] or "Not Set")
