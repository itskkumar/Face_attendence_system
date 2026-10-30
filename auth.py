"""
auth.py - Simple authentication and session management.

Provides basic username/password authentication with role-based access control.
For production use, integrate with your organization's SSO/LDAP system.
"""
import hashlib
import secrets
from typing import Optional, Tuple

import streamlit as st

from database import Store


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hash password with salt using SHA-256."""
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return pwd_hash, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored hash."""
    pwd_hash, _ = hash_password(password, salt)
    return pwd_hash == stored_hash


def create_default_admin(store: Store):
    """Create default admin user if no users exist."""
    with store._conn() as c:
        count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            # Create default admin: username=admin, password=admin123
            pwd_hash, salt = hash_password("admin123")
            c.execute(
                "INSERT INTO users(username, password_hash, role, created_at) VALUES(?,?,?,datetime('now'))",
                (f"admin:{salt}", pwd_hash, "admin")
            )
            return True
    return False


def authenticate(store: Store, username: str, password: str) -> Optional[str]:
    """Authenticate user and return role if successful."""
    with store._conn() as c:
        rows = c.execute("SELECT username, password_hash, role FROM users").fetchall()
        for row in rows:
            stored_username_salt = row['username']
            if ':' in stored_username_salt:
                stored_username, salt = stored_username_salt.split(':', 1)
            else:
                continue  # Invalid format

            if stored_username == username:
                if verify_password(password, row['password_hash'], salt):
                    return row['role']
    return None


def check_authentication() -> Optional[str]:
    """Check if user is authenticated in session. Returns role or None."""
    return st.session_state.get('authenticated_role', None)


def require_auth(required_role: str = "viewer"):
    """Decorator/function to require authentication for a page."""
    role = check_authentication()

    if role is None:
        st.warning("🔒 Please log in to access this page")
        st.stop()

    if required_role == "admin" and role != "admin":
        st.error("🚫 Admin access required")
        st.stop()

    return role


def login_page(store: Store):
    """Display login form."""
    st.title("🔐 Login")

    # Create default admin if needed
    if create_default_admin(store):
        st.info("ℹ️ Default admin account created: username=`admin`, password=`admin123`")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

        if submitted:
            role = authenticate(store, username, password)
            if role:
                st.session_state['authenticated_role'] = role
                st.session_state['authenticated_user'] = username
                st.success(f"✅ Logged in as {username} ({role})")
                st.rerun()
            else:
                st.error("❌ Invalid username or password")


def logout():
    """Logout current user."""
    if 'authenticated_role' in st.session_state:
        del st.session_state['authenticated_role']
    if 'authenticated_user' in st.session_state:
        del st.session_state['authenticated_user']


def get_current_user() -> str:
    """Get current authenticated username."""
    return st.session_state.get('authenticated_user', 'anonymous')


def show_auth_sidebar(store: Store):
    """Display authentication status in sidebar."""
    role = check_authentication()

    if role:
        user = get_current_user()
        st.sidebar.markdown(f"**👤 User:** {user}")
        st.sidebar.markdown(f"**🎭 Role:** {role}")

        if st.sidebar.button("🚪 Logout", use_container_width=True):
            logout()
            st.rerun()
    else:
        if st.sidebar.button("🔐 Login", use_container_width=True, type="primary"):
            st.session_state['show_login'] = True
