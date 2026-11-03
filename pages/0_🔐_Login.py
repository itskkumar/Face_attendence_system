"""
Login page with glass morphism design
"""
import streamlit as st
from auth import login_page, check_authentication, logout
from ui_common import get_store

st.set_page_config(page_title="Login", page_icon="🔐", layout="centered")

# Glass morphism CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    * {
        font-family: 'Inter', sans-serif;
    }

    /* Background gradient animation */
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

    /* Glass morphism container */
    .main .block-container {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        padding: 3rem 2rem;
        max-width: 500px;
        margin: 0 auto;
        animation: fadeIn 0.6s ease-in;
    }

    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Title styling */
    h1 {
        color: white !important;
        text-align: center;
        font-weight: 700;
        text-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin-bottom: 2rem;
        animation: slideDown 0.6s ease-out;
    }

    @keyframes slideDown {
        from { opacity: 0; transform: translateY(-20px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Input fields */
    .stTextInput > div > div > input {
        background: rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.3);
        border-radius: 12px;
        color: white;
        padding: 0.75rem 1rem;
        font-size: 1rem;
        transition: all 0.3s ease;
    }

    .stTextInput > div > div > input:focus {
        background: rgba(255, 255, 255, 0.3);
        border: 1px solid rgba(255, 255, 255, 0.5);
        box-shadow: 0 0 20px rgba(255, 255, 255, 0.3);
        transform: scale(1.02);
    }

    .stTextInput > div > div > input::placeholder {
        color: rgba(255, 255, 255, 0.6);
    }

    .stTextInput > label {
        color: white !important;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }

    /* Button styling */
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 12px;
        padding: 0.75rem 2rem;
        font-size: 1rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        width: 100%;
    }

    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
    }

    .stButton > button:active {
        transform: translateY(0);
    }

    /* Info box */
    .stAlert {
        background: rgba(255, 255, 255, 0.15);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.2);
        border-radius: 12px;
        color: white;
        animation: fadeIn 0.5s ease-in;
    }

    /* Form container */
    .stForm {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 15px;
        padding: 1.5rem;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }

    /* Hide streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Success/Error messages */
    .stSuccess {
        background: rgba(16, 185, 129, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(16, 185, 129, 0.4);
        color: white;
        border-radius: 12px;
        animation: slideIn 0.4s ease-out;
    }

    .stError {
        background: rgba(239, 68, 68, 0.2);
        backdrop-filter: blur(5px);
        border: 1px solid rgba(239, 68, 68, 0.4);
        color: white;
        border-radius: 12px;
        animation: shake 0.5s ease-out;
    }

    @keyframes slideIn {
        from { opacity: 0; transform: translateX(-20px); }
        to { opacity: 1; transform: translateX(0); }
    }

    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-10px); }
        75% { transform: translateX(10px); }
    }

    /* Logo/Icon styling */
    .login-icon {
        text-align: center;
        font-size: 4rem;
        margin-bottom: 1rem;
        animation: float 3s ease-in-out infinite;
    }

    @keyframes float {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
    }
</style>
""", unsafe_allow_html=True)

# Check if already logged in
role = check_authentication()

if role:
    st.markdown("<div class='login-icon'>✅</div>", unsafe_allow_html=True)
    st.title("Already Logged In")

    user = st.session_state.get('authenticated_user', 'User')
    st.success(f"👤 Welcome back, **{user}** ({role})")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🏠 Go to Dashboard", use_container_width=True):
            st.switch_page("dashboard.py")
    with col2:
        if st.button("🚪 Logout", use_container_width=True):
            logout()
            st.rerun()
else:
    st.markdown("<div class='login-icon'>🔐</div>", unsafe_allow_html=True)

    store = get_store()
    login_page(store)

    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: rgba(255,255,255,0.7); font-size: 0.9rem;'>
        <p><strong>Default Credentials:</strong></p>
        <p>Admin: <code>admin</code> / <code>admin123</code></p>
        <p>Students can use their roll number as username</p>
    </div>
    """, unsafe_allow_html=True)
