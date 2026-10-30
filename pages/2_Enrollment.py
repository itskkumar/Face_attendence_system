"""
pages/2_Enrollment.py - register students from the browser (camera or uploaded photos).

Several quality-checked samples per person (slightly different head angles) make recognition far
more robust than one photo. The browser camera avoids the macOS Terminal-camera-permission step.
"""
import cv2
import numpy as np
import pandas as pd
import streamlit as st

from config import DEFAULT_SETTINGS
from enrollment_core import analyze_face_for_enrollment
from ui_common import get_engine, get_store

st.set_page_config(page_title="Enrollment", page_icon="🧬", layout="wide")
st.title("🧬 Student Enrollment")

engine = get_engine()
store = get_store()
settings = DEFAULT_SETTINGS

samples = st.session_state.setdefault("enroll_samples", [])
cam_n = st.session_state.setdefault("enroll_cam_n", 0)


def decode(raw: bytes):
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


tab_add, tab_manage = st.tabs(["Enrol a student", "Enrolled students"])

with tab_add:
    st.markdown("### Basic Information")
    c1, c2 = st.columns(2)
    name = c1.text_input("Full name*")
    roll = c2.text_input("Roll number*")

    st.markdown("### Additional Details (Optional)")
    c3, c4, c5 = st.columns(3)
    email = c3.text_input("Email", placeholder="student@example.com")
    phone = c4.text_input("Phone", placeholder="+1234567890")
    department = c5.text_input("Department", placeholder="Computer Science")

    c6, c7 = st.columns(2)
    batch = c6.text_input("Batch/Year", placeholder="2024")
    expected_time = c7.text_input("Expected Arrival Time", placeholder="09:00")

    st.divider()
    st.markdown("### Face Photos")
    st.caption("Collect **3-5 photos**: straight on, then turned slightly left / right / up / down. Only the "
               "student should be in the picture; good light, no sunglasses.")
    method = st.radio("Photo source", ["Camera (browser)", "Upload photos"], horizontal=True)

    if method == "Camera (browser)":
        shot = st.camera_input("Take a photo", key=f"enroll_cam_{cam_n}")
        if shot is not None:
            sample, reason = analyze_face_for_enrollment(engine, decode(shot.getvalue()), settings)
            if sample is None:
                st.warning(f"Photo rejected: {reason}")
            else:
                st.success(f"Good photo (sharpness {sample.blur:.0f}, frontal-ness {sample.pose:.2f})")
                if st.button("➕ Add this photo"):
                    samples.append(sample)
                    st.session_state["enroll_cam_n"] = cam_n + 1       # resets the camera widget
                    st.rerun()
    else:
        files = st.file_uploader("Photos of the student", type=["jpg", "jpeg", "png"],
                                 accept_multiple_files=True)
        if files and st.button("🔍 Check and add these photos"):
            for f in files:
                img = decode(f.getvalue())
                sample, reason = analyze_face_for_enrollment(engine, img, settings) if img is not None \
                    else (None, "unreadable image")
                if sample is None:
                    st.warning(f"{f.name}: rejected - {reason}")
                else:
                    samples.append(sample)
            st.rerun()

    st.markdown(f"**Accepted samples: {len(samples)}**")
    if samples:
        st.image([cv2.cvtColor(s.aligned, cv2.COLOR_BGR2RGB) for s in samples], width=96,
                 caption=[f"sharp {s.blur:.0f}" for s in samples])
    b1, b2, _ = st.columns([1, 1, 4])
    if b2.button("🗑 Clear samples", disabled=not samples):
        samples.clear()
        st.rerun()
    if b1.button("✅ Save student", type="primary", disabled=not samples):
        if not name.strip() or not roll.strip():
            st.error("Name and roll number are required.")
        else:
            if len(samples) < 3:
                st.info("Saved with fewer than 3 photos - recognition is more reliable with 3-5.")
            embs = [s.embedding for s in samples]
            dup = store.find_duplicate_identity(embs, roll)
            if dup:
                st.error(f"Refused: this face already matches **{dup[1]}** ({dup[0]}) "
                         f"with similarity {dup[2]:.2f}. Delete or correct that record first.")
            else:
                _, n = store.add_student(
                    roll, name, embs, [s.quality for s in samples],
                    email=email, phone=phone, department=department,
                    batch=batch, expected_time=expected_time
                )
                st.success(f"Saved **{name.strip()}** ({roll.strip().upper()}) with {n} template(s). "
                           "Running streams pick this up within a couple of seconds.")
                samples.clear()

with tab_manage:
    rows = store.list_students()
    if rows:
        st.dataframe(pd.DataFrame(rows).rename(columns={
            "roll_number": "Roll Number", "name": "Name", "created_at": "Enrolled", "templates": "Templates"}),
            hide_index=True)
        who = st.selectbox("Remove a student", [""] + [f"{r['roll_number']} - {r['name']}" for r in rows])
        sure = st.checkbox("I understand this deletes the face data (attendance history is kept)")
        if st.button("Delete selected student", disabled=not (who and sure)):
            store.delete_student(who.split(" - ")[0])
            st.success("Deleted.")
            st.rerun()
    else:
        st.info("No students enrolled yet.")
