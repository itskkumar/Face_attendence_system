"""
pages/7_Multi_Camera.py - Multi-camera configuration and monitoring.

Features: Configure multiple cameras, assign labels, view all feeds,
monitor per-camera statistics, and manage camera settings.
"""
import json
import os

import pandas as pd
import streamlit as st

from config import DATA_DIR, RTSP_URL
from ui_common import get_store

st.set_page_config(page_title="Multi-Camera Setup", page_icon="📹", layout="wide")
st.title("📹 Multi-Camera Configuration")

store = get_store()

# Camera configuration file
CAMERA_CONFIG_FILE = os.path.join(DATA_DIR, "cameras.json")


def load_camera_config():
    """Load camera configuration from file."""
    if os.path.exists(CAMERA_CONFIG_FILE):
        with open(CAMERA_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_camera_config(config):
    """Save camera configuration to file."""
    with open(CAMERA_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


# Load existing config
camera_config = load_camera_config()

# Tabs
tab_config, tab_stats, tab_guide = st.tabs(["Configure Cameras", "Camera Statistics", "Setup Guide"])

# ============================================================================
# TAB 1: Configure Cameras
# ============================================================================
with tab_config:
    st.subheader("Camera Configuration")

    st.info("""
    💡 **How it works:**
    - Add cameras with unique labels (e.g., "Main Entrance", "Side Gate", "Cafeteria")
    - Each camera can be a webcam, RTSP stream, or video file
    - Camera labels will appear in attendance logs for location tracking
    """)

    # Add new camera
    st.markdown("### Add New Camera")

    with st.form("add_camera_form"):
        col1, col2 = st.columns(2)

        with col1:
            camera_label = st.text_input(
                "Camera Label*",
                placeholder="e.g., Main Entrance",
                help="Unique name for this camera location"
            )
            camera_type = st.selectbox(
                "Camera Type",
                ["RTSP Stream", "Webcam", "Video File Path"]
            )

        with col2:
            if camera_type == "RTSP Stream":
                camera_source = st.text_input(
                    "RTSP URL*",
                    placeholder="rtsp://username:password@192.168.1.100:554/stream1"
                )
            elif camera_type == "Webcam":
                camera_source = st.number_input("Webcam Index", min_value=0, max_value=10, value=0)
                camera_source = f"webcam:{camera_source}"
            else:
                camera_source = st.text_input(
                    "Video File Path*",
                    placeholder="/path/to/video.mp4"
                )

            enabled = st.checkbox("Enabled", value=True)

        description = st.text_area(
            "Description (optional)",
            placeholder="e.g., Main entrance facing north, covers parking lot"
        )

        submitted = st.form_submit_button("➕ Add Camera", type="primary")

        if submitted:
            if not camera_label or not camera_source:
                st.error("Camera label and source are required")
            elif camera_label in camera_config:
                st.error(f"Camera '{camera_label}' already exists. Use a unique label.")
            else:
                camera_config[camera_label] = {
                    "type": camera_type,
                    "source": str(camera_source),
                    "description": description,
                    "enabled": enabled
                }
                save_camera_config(camera_config)
                st.success(f"✅ Added camera: {camera_label}")
                st.rerun()

    st.divider()

    # Manage existing cameras
    st.markdown("### Configured Cameras")

    if camera_config:
        for label, config in camera_config.items():
            with st.expander(f"{'✅' if config.get('enabled') else '⏸️'} {label}", expanded=False):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.markdown(f"**Type:** {config['type']}")
                    st.markdown(f"**Source:** `{config['source']}`")
                    if config.get('description'):
                        st.markdown(f"**Description:** {config['description']}")
                    st.markdown(f"**Status:** {'🟢 Enabled' if config.get('enabled') else '⏸️ Disabled'}")

                with col2:
                    # Toggle enable/disable
                    if st.button(f"{'⏸️ Disable' if config.get('enabled') else '▶️ Enable'}", key=f"toggle_{label}"):
                        camera_config[label]['enabled'] = not config.get('enabled', True)
                        save_camera_config(camera_config)
                        st.rerun()

                    # Delete camera
                    if st.button(f"🗑️ Delete", key=f"delete_{label}", type="secondary"):
                        del camera_config[label]
                        save_camera_config(camera_config)
                        st.success(f"Deleted {label}")
                        st.rerun()

        # Export camera config
        st.divider()
        config_json = json.dumps(camera_config, indent=2)
        st.download_button(
            "⬇ Download Camera Configuration (JSON)",
            config_json,
            "camera_config.json",
            "application/json"
        )

    else:
        st.info("No cameras configured yet. Add your first camera above.")

# ============================================================================
# TAB 2: Camera Statistics
# ============================================================================
with tab_stats:
    st.subheader("Per-Camera Statistics")

    # Get camera statistics from database
    camera_stats = store.get_camera_stats()

    if camera_stats:
        df_stats = pd.DataFrame(camera_stats)

        # Overall summary
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Cameras in Use", len(df_stats))
        col2.metric("Total Entries", df_stats['total'].sum())
        col3.metric("Unique Persons Detected", df_stats['unique_persons'].sum())

        st.divider()

        # Detailed stats table
        st.markdown("### Detailed Camera Activity")

        # Add status indicator for configured cameras
        df_display = df_stats.copy()
        df_display['configured'] = df_display['camera_label'].apply(
            lambda x: '✅ Yes' if x in camera_config else '❌ No'
        )

        st.dataframe(
            df_display,
            hide_index=True,
            use_container_width=True,
            column_config={
                'camera_label': st.column_config.TextColumn("Camera Label", width="medium"),
                'total': st.column_config.NumberColumn("Total Entries", width="small"),
                'unique_persons': st.column_config.NumberColumn("Unique Persons", width="small"),
                'configured': st.column_config.TextColumn("Configured", width="small")
            }
        )

        # Bar chart - entries per camera
        st.markdown("### Activity by Camera")
        st.bar_chart(df_stats.set_index('camera_label')['total'])

        # Download stats
        csv = df_stats.to_csv(index=False).encode('utf-8')
        st.download_button(
            "⬇ Download Camera Statistics (CSV)",
            csv,
            "camera_statistics.csv",
            "text/csv"
        )

    else:
        st.info("No camera activity recorded yet. Start processing video feeds to see statistics.")

# ============================================================================
# TAB 3: Setup Guide
# ============================================================================
with tab_guide:
    st.subheader("Multi-Camera Setup Guide")

    st.markdown("""
    ## 🎥 How to Run Multiple Cameras

    ### Method 1: Browser (Recommended for Testing)
    1. Configure cameras in the **Configure Cameras** tab above
    2. Go to **Live Feed** page in the sidebar
    3. Select your camera from the dropdown
    4. The camera label will be automatically recorded in logs

    ### Method 2: Command Line (Recommended for Production)

    Run multiple camera feeds simultaneously using the CLI tool with different camera labels:

    ```bash
    # Terminal 1 - Main entrance camera
    python inference.py --source rtsp://192.168.1.100:554/stream1 --camera-label "Main Entrance"

    # Terminal 2 - Side gate camera
    python inference.py --source rtsp://192.168.1.101:554/stream1 --camera-label "Side Gate"

    # Terminal 3 - Parking lot camera
    python inference.py --source rtsp://192.168.1.102:554/stream1 --camera-label "Parking Lot"
    ```

    ### Method 3: Background Services (Production Deployment)

    Create a systemd service (Linux) or use `screen`/`tmux` for each camera:

    **Using screen:**
    ```bash
    # Start first camera in background
    screen -dmS camera1 python inference.py --source rtsp://cam1 --camera-label "Main Entrance"

    # Start second camera in background
    screen -dmS camera2 python inference.py --source rtsp://cam2 --camera-label "Side Gate"

    # List running sessions
    screen -ls

    # Attach to a session to view
    screen -r camera1
    ```

    **Using Docker Compose (Advanced):**
    ```yaml
    version: '3.8'
    services:
      camera1:
        build: .
        command: python inference.py --source rtsp://cam1 --camera-label "Main Entrance"
        restart: always

      camera2:
        build: .
        command: python inference.py --source rtsp://cam2 --camera-label "Side Gate"
        restart: always
    ```

    ## 📋 Camera Configuration Tips

    ### RTSP Cameras:
    - **Format:** `rtsp://username:password@ip:port/stream`
    - **Example:** `rtsp://admin:pass123@192.168.1.100:554/Streaming/Channels/101`
    - **Pro Tip:** Use substreams (e.g., `/102`) for lower CPU usage
    - **Test First:** Open in VLC (Media → Open Network Stream) before configuring

    ### Webcams:
    - **Index 0:** Usually built-in laptop camera
    - **Index 1+:** External USB cameras
    - **Find Index:** Try 0, 1, 2 until you find the right camera

    ### Network Considerations:
    - **Bandwidth:** HD stream = ~2-8 Mbps per camera
    - **Latency:** RTSP over TCP reduces frame corruption
    - **VLANs:** Keep camera traffic on separate network if possible

    ## 🔧 Performance Optimization

    ### For Multiple Cameras:
    1. **Lower resolution:** Use substreams instead of main streams
    2. **Adjust detection frequency:** Set `detect_every_n` higher (e.g., 3-5)
    3. **Dedicated hardware:** Use GPU if available, or separate machines per camera
    4. **Monitor resources:** Check System Health page regularly

    ### Recommended Hardware:
    - **1-2 cameras:** Laptop/Desktop with modern CPU
    - **3-5 cameras:** Desktop with GPU (NVIDIA recommended)
    - **6+ cameras:** Multiple machines or server-grade GPU

    ## 📊 Monitoring

    Once cameras are running:
    - **Dashboard:** Shows combined counts from all cameras
    - **Search Page:** Filter by camera label
    - **Analytics Page:** View per-camera statistics
    - **System Health:** Monitor performance metrics

    ## ⚠️ Troubleshooting

    ### Camera Won't Connect:
    - Check IP address and credentials
    - Test RTSP URL in VLC first
    - Verify network connectivity (`ping camera_ip`)
    - Check firewall rules (port 554 for RTSP)

    ### Poor Performance:
    - Reduce `process_width` in config
    - Increase `detect_every_n` (detect less frequently)
    - Use camera's substream instead of main stream
    - Close other applications

    ### Missing Camera Labels:
    - Ensure you're passing `--camera-label` flag when running CLI
    - Check that camera is configured in this page
    - Verify logs show correct camera label

    ## 📞 Need Help?

    - **Documentation:** Check project README.md
    - **Test RTSP:** Use VLC Media Player to verify camera URLs
    - **Network Tools:** Use `ffmpeg` or `ffplay` to test streams
    """)

    st.divider()

    st.markdown("### 🎯 Quick Reference: Camera Label Usage")

    st.code("""
# Python API
store.log_attendance(
    roll_number="2024-CS-001",
    name="John Doe",
    student_id=1,
    similarity=0.85,
    direction="ENTRY",
    source="rtsp",
    cooldown_seconds=300,
    camera_label="Main Entrance"  # ← Camera label here
)

# Command Line
python inference.py \\
    --source rtsp://192.168.1.100:554/stream1 \\
    --camera-label "Main Entrance"  # ← Camera label here
""", language="python")

# Footer
st.divider()
st.caption("💡 **Tip:** Configure all cameras here, then start them via CLI for production use")
