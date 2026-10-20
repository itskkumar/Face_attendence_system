"""
dashboard.py - Streamlit entry point (Module C).   Run:  streamlit run dashboard.py

Shows today's unique-entry count (large), a live table of the most recent entries and an
hourly chart. Auto-refreshes every few seconds, so it reflects whatever inference.py or the
Live Feed page is logging. Other pages live in the sidebar.
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
scans_today = store.today_total_scans()
students = store.list_students()
recent = store.recent_entries(25)
hourly = store.hourly_counts_today()

st.title("🎓 Real-Time Face Attendance Dashboard")
st.caption(f"Updated {dt.datetime.now():%Y-%m-%d %H:%M:%S}  ·  refreshes every 3 s  ·  "
           "use the sidebar pages for the Live Feed and Enrollment")

big, side = st.columns([2, 3])
with big:
    st.markdown("##### Unique people entered today")
    st.markdown(f"<div style='font-size:7rem;line-height:1;font-weight:800'>{unique_today}</div>",
                unsafe_allow_html=True)
with side:
    c1, c2 = st.columns(2)
    c1.metric("Total log entries today", scans_today)
    c2.metric("Enrolled students", len(students))
    st.markdown("##### Entries by hour (today)")
    if hourly:
        st.bar_chart(pd.DataFrame(hourly, columns=["Hour", "Entries"]).set_index("Hour"))
    else:
        st.info("No entries yet today.")

st.divider()
st.subheader("Most recent entries")
if recent:
    df = pd.DataFrame(recent).rename(columns={
        "name": "Name", "roll_number": "Roll Number", "timestamp": "Entry Time",
        "direction": "Direction", "similarity": "Match", "source": "Source"})
    df["Match"] = df["Match"].map(lambda v: f"{v:.2f}" if v is not None else "")
    st.dataframe(df[["Name", "Roll Number", "Entry Time", "Direction", "Match", "Source"]], hide_index=True)
else:
    st.info("Nothing logged yet. Enrol someone, then start the Live Feed page or `python inference.py`.")

logs = store.all_logs()
if logs:
    st.download_button("⬇ Download full attendance log (CSV)",
                       pd.DataFrame(logs).to_csv(index=False).encode("utf-8"),
                       file_name=f"attendance_{dt.datetime.now():%Y%m%d_%H%M%S}.csv", mime="text/csv")
