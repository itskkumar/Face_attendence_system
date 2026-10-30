"""
pages/5_Student_Management.py - Enhanced student data management.

Features: bulk CSV import, student profiles with extra fields,
edit student information, duplicate detection alerts.
"""
import io

import pandas as pd
import streamlit as st

from ui_common import get_store

st.set_page_config(page_title="Student Management", page_icon="👥", layout="wide")
st.title("👥 Student Management")

store = get_store()

# Tabs for different management functions
tab_bulk, tab_edit, tab_export = st.tabs(["Bulk Import", "Edit Students", "Export Data"])

# ============================================================================
# TAB 1: Bulk Import
# ============================================================================
with tab_bulk:
    st.subheader("Bulk Import Student Metadata")

    st.info("""
    📋 **How it works:**
    - Upload a CSV file with student metadata (roll number, name, email, phone, etc.)
    - Students must already be enrolled with photos (use Enrollment page first)
    - This updates their profile information only (email, phone, department, batch, expected time)
    """)

    # Show CSV template
    st.markdown("### CSV Template")
    st.markdown("""
    Your CSV should have these columns:
    - `roll_number` (required) - Student roll number
    - `name` (required) - Full name
    - `email` - Email address
    - `phone` - Phone number
    - `department` - Department/Class
    - `batch` - Batch/Year
    - `expected_time` - Expected arrival time (HH:MM format)
    """)

    # Download template
    template_df = pd.DataFrame({
        'roll_number': ['2024-CS-001', '2024-CS-002'],
        'name': ['John Doe', 'Jane Smith'],
        'email': ['john@example.com', 'jane@example.com'],
        'phone': ['+1234567890', '+1234567891'],
        'department': ['Computer Science', 'Computer Science'],
        'batch': ['2024', '2024'],
        'expected_time': ['09:00', '09:00']
    })

    csv_template = template_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        "⬇ Download CSV Template",
        csv_template,
        "student_import_template.csv",
        "text/csv"
    )

    st.divider()

    # File uploader
    st.markdown("### Upload Student Data")
    uploaded_file = st.file_uploader("Choose a CSV file", type=['csv'])

    if uploaded_file is not None:
        try:
            # Read CSV
            df = pd.read_csv(uploaded_file)

            st.markdown(f"**Preview:** Found {len(df)} records")
            st.dataframe(df.head(10), hide_index=True)

            # Validate required columns
            required_cols = ['roll_number', 'name']
            missing_cols = [col for col in required_cols if col not in df.columns]

            if missing_cols:
                st.error(f"❌ Missing required columns: {', '.join(missing_cols)}")
            else:
                # Process button
                if st.button("🚀 Import Students", type="primary"):
                    with st.spinner("Importing students..."):
                        # Convert to list of dicts
                        students_data = df.to_dict('records')

                        # Bulk import
                        success, errors, error_msgs = store.bulk_import_students(students_data)

                        # Show results
                        col1, col2 = st.columns(2)
                        col1.metric("✅ Successful", success)
                        col2.metric("❌ Errors", errors)

                        if success > 0:
                            st.success(f"Successfully imported metadata for {success} students!")

                        if error_msgs:
                            st.error("**Import Errors:**")
                            for msg in error_msgs[:10]:  # Show first 10 errors
                                st.text(f"• {msg}")
                            if len(error_msgs) > 10:
                                st.text(f"... and {len(error_msgs) - 10} more errors")

        except Exception as e:
            st.error(f"Error reading CSV file: {str(e)}")
            st.info("Make sure your CSV is properly formatted and uses UTF-8 encoding")

# ============================================================================
# TAB 2: Edit Students
# ============================================================================
with tab_edit:
    st.subheader("Edit Student Information")

    students = store.list_students()

    if students:
        # Student selector
        student_options = [""] + [f"{s['roll_number']} - {s['name']}" for s in students]
        selected = st.selectbox("Select student to edit", student_options)

        if selected:
            roll_number = selected.split(" - ")[0]

            # Get current profile
            profile = store.get_student_profile(roll_number)

            if profile:
                st.markdown("### Current Information")

                # Edit form
                with st.form("edit_student_form"):
                    col1, col2 = st.columns(2)

                    with col1:
                        new_name = st.text_input("Name", value=profile['name'])
                        new_email = st.text_input("Email", value=profile.get('email', ''))
                        new_phone = st.text_input("Phone", value=profile.get('phone', ''))

                    with col2:
                        new_dept = st.text_input("Department", value=profile.get('department', ''))
                        new_batch = st.text_input("Batch/Year", value=profile.get('batch', ''))
                        new_time = st.text_input("Expected Time (HH:MM)", value=profile.get('expected_time', ''))

                    submitted = st.form_submit_button("💾 Save Changes", type="primary")

                    if submitted:
                        try:
                            # Update student (keeping existing embeddings)
                            # We need to get embeddings first
                            with store._conn() as c:
                                c.execute(
                                    """UPDATE students
                                       SET name=?, email=?, phone=?, department=?, batch=?, expected_time=?
                                       WHERE roll_number=?""",
                                    (new_name, new_email, new_phone, new_dept, new_batch, new_time, roll_number)
                                )

                            st.success(f"✅ Updated profile for {new_name}")
                            st.rerun()

                        except Exception as e:
                            st.error(f"Error updating student: {str(e)}")

                # Delete button (outside form)
                st.divider()
                st.markdown("### Danger Zone")

                col_del1, col_del2 = st.columns([3, 1])
                with col_del1:
                    delete_confirm = st.checkbox(
                        f"I understand this will delete all face data for {profile['name']}"
                    )
                with col_del2:
                    if st.button("🗑 Delete Student", disabled=not delete_confirm, type="secondary"):
                        if store.delete_student(roll_number):
                            store.log_audit("admin", "delete_student", f"Deleted student {roll_number}")
                            st.success(f"Deleted {profile['name']}")
                            st.rerun()
                        else:
                            st.error("Failed to delete student")

    else:
        st.info("No students enrolled yet. Use the Enrollment page to add students.")

# ============================================================================
# TAB 3: Export Data
# ============================================================================
with tab_export:
    st.subheader("Export Student Data")

    students = store.list_students()

    if students:
        st.markdown(f"**Total Students:** {len(students)}")

        # Get full profiles with attendance stats
        full_data = []
        for student in students:
            profile = store.get_student_profile(student['roll_number'])
            if profile:
                # Calculate attendance percentage
                attendance_pct = store.get_attendance_percentage(profile['roll_number'], 30)
                full_data.append({
                    'roll_number': profile['roll_number'],
                    'name': profile['name'],
                    'email': profile.get('email', ''),
                    'phone': profile.get('phone', ''),
                    'department': profile.get('department', ''),
                    'batch': profile.get('batch', ''),
                    'expected_time': profile.get('expected_time', ''),
                    'total_attendance': profile['total_attendance'],
                    'attendance_30d_%': f"{attendance_pct:.1f}",
                    'enrolled_date': profile['created_at']
                })

        df_export = pd.DataFrame(full_data)

        # Preview
        st.dataframe(df_export, hide_index=True, use_container_width=True)

        # Export options
        col1, col2 = st.columns(2)

        with col1:
            # CSV export
            csv = df_export.to_csv(index=False).encode('utf-8')
            st.download_button(
                "⬇ Download as CSV",
                csv,
                f"students_export_{pd.Timestamp.now():%Y%m%d_%H%M%S}.csv",
                "text/csv",
                use_container_width=True
            )

        with col2:
            # Excel export (requires openpyxl)
            try:
                import openpyxl
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='Students')
                buffer.seek(0)

                st.download_button(
                    "⬇ Download as Excel",
                    buffer,
                    f"students_export_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            except ImportError:
                st.info("📦 Excel export requires openpyxl: `pip install openpyxl`")

    else:
        st.info("No students to export. Enroll students first.")

# Footer
st.divider()
st.caption("💡 **Tip:** Always enroll students with photos first before importing metadata")
