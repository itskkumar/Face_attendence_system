"""
Admin User Management page with glass morphism design
"""
import streamlit as st
from auth import check_authentication, require_auth, hash_password
from ui_common import get_store

st.set_page_config(page_title="User Management", page_icon="👥", layout="wide")

# Require admin authentication
role = require_auth("admin")

store = get_store()

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

    h1, h2, h3 {
        color: white !important;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* Glass morphism form */
    .stForm {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 1.5rem;
    }

    /* Input fields */
    .stTextInput > div > div > input,
    .stSelectbox > div > div > div {
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

    .stTextInput > label,
    .stSelectbox > label {
        color: white !important;
        font-weight: 500;
    }

    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
    }

    /* Dataframe styling */
    .stDataFrame {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
    }

    /* Alert boxes */
    .stAlert {
        background: rgba(255, 255, 255, 0.15);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 12px;
        color: white;
    }

    .stSuccess {
        background: rgba(16, 185, 129, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(16, 185, 129, 0.4);
    }

    .stError {
        background: rgba(239, 68, 68, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(239, 68, 68, 0.4);
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

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.title("👥 User Management")
st.caption("Manage admin and student accounts")

# Tabs
tab1, tab2, tab3 = st.tabs(["📋 All Users", "➕ Add User", "🔄 Sync Students"])

with tab1:
    st.subheader("Registered Users")

    with store._conn() as c:
        users = c.execute("SELECT username, role, created_at FROM users ORDER BY created_at DESC").fetchall()

    if users:
        user_data = []
        for user in users:
            username_clean = user["username"].split(":")[0] if ":" in user["username"] else user["username"]
            user_data.append({
                "Username": username_clean,
                "Role": user["role"].upper(),
                "Created At": user["created_at"]
            })

        import pandas as pd
        df = pd.DataFrame(user_data)
        st.dataframe(df, hide_index=True, use_container_width=True)

        # Delete user section
        st.markdown("---")
        st.subheader("Delete User")
        delete_username = st.selectbox("Select user to delete", [u["Username"] for u in user_data])

        if st.button("🗑️ Delete User", type="secondary"):
            with store._conn() as c:
                # Find the user with salt
                user_to_delete = c.execute("SELECT username FROM users").fetchall()
                for u in user_to_delete:
                    if u["username"].startswith(f"{delete_username}:"):
                        c.execute("DELETE FROM users WHERE username = ?", (u["username"],))
                        st.success(f"✅ User '{delete_username}' deleted successfully")
                        st.rerun()
                        break
    else:
        st.info("No users found")

with tab2:
    st.subheader("Add New User")

    with st.form("add_user_form"):
        new_username = st.text_input("Username", placeholder="Enter username")
        new_password = st.text_input("Password", type="password", placeholder="Enter password")
        new_role = st.selectbox("Role", ["admin", "student"])

        submitted = st.form_submit_button("➕ Add User", use_container_width=True)

        if submitted:
            if new_username and new_password:
                pwd_hash, salt = hash_password(new_password)
                try:
                    with store._conn() as c:
                        c.execute(
                            "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,datetime('now'))",
                            (f"{new_username}:{salt}", pwd_hash, new_role)
                        )
                    st.success(f"✅ User '{new_username}' created successfully with role '{new_role}'")
                except Exception as e:
                    st.error(f"❌ Error creating user: {str(e)}")
            else:
                st.error("❌ Please fill in all fields")

with tab3:
    st.subheader("Sync Students to Users")
    st.caption("This will create user accounts for all enrolled students who don't have one")

    if st.button("🔄 Sync All Students", type="primary", use_container_width=True):
        students = store.list_students()
        synced_count = 0

        with st.spinner("Syncing students..."):
            for student in students:
                roll_number = student["roll_number"]

                # Check if user already exists
                with store._conn() as c:
                    existing = c.execute(
                        "SELECT username FROM users WHERE username LIKE ?",
                        (f"{roll_number}:%",)
                    ).fetchone()

                    if not existing:
                        # Create user with default password "student123"
                        pwd_hash, salt = hash_password("student123")
                        try:
                            c.execute(
                                "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,datetime('now'))",
                                (f"{roll_number}:{salt}", pwd_hash, "student")
                            )
                            synced_count += 1
                        except:
                            pass

        if synced_count > 0:
            st.success(f"✅ Synced {synced_count} student(s). Default password: 'student123'")
        else:
            st.info("ℹ️ All students already have user accounts")

# Quick stats
st.markdown("---")
st.subheader("📊 User Statistics")

with store._conn() as c:
    total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    admin_count = c.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
    student_count = c.execute("SELECT COUNT(*) FROM users WHERE role = 'student'").fetchone()[0]

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Users", total_users)
with col2:
    st.metric("Admins", admin_count)
with col3:
    st.metric("Students", student_count)
