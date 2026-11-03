"""
Mathematical Pipeline Inspector - Interactive demonstration of vision math.

For viva demonstrations: shows SVD transformation matrix, 2D FFT spectrum,
quality gates, and Kalman state vectors.
"""
import streamlit as st
import numpy as np
import cv2
from PIL import Image
import io

from vision_math import compute_fft_liveness, align_face, laplacian_variance, pose_score, umeyama_similarity, ARCFACE_REF
from ui_common import get_engine, get_store
from auth import check_authentication, require_auth

st.set_page_config(page_title="Math Inspector", page_icon="🔬", layout="wide")

# Check authentication (admin only for this technical page)
role = check_authentication()
if not role:
    st.warning("🔒 Please log in to access the Math Inspector")
    if st.button("Go to Login Page", type="primary"):
        st.switch_page("pages/0_🔐_Login.py")
    st.stop()

# Glass morphism CSS (matching dashboard theme)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    * { font-family: 'Inter', sans-serif; }

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

    h1, h2, h3 { color: white !important; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }

    .metric-card {
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        border: 1px solid rgba(255, 255, 255, 0.2);
        padding: 1rem;
        margin: 0.5rem 0;
    }

    .stMetric { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); border-radius: 10px; padding: 1rem; }
    .stMetric label { color: rgba(255, 255, 255, 0.8) !important; }
    .stMetric [data-testid="stMetricValue"] { color: white !important; }

    code { background: rgba(255, 255, 255, 0.2) !important; color: white !important; }

    [data-testid="stSidebar"] { background: rgba(255, 255, 255, 0.1); backdrop-filter: blur(10px); }
    [data-testid="stSidebar"] * { color: white !important; }

    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.title("🔬 Mathematical Pipeline Inspector")
st.caption("Interactive demonstration of vision mathematics for face recognition")

# Upload or capture test image
st.markdown("### 📸 Input")
input_method = st.radio("Input method:", ["Upload Image", "Use Webcam"], horizontal=True)

img_bgr = None

if input_method == "Upload Image":
    uploaded = st.file_uploader("Upload test face image", type=['jpg', 'png', 'jpeg'])

    if uploaded:
        file_bytes = np.asarray(bytearray(uploaded.read()), dtype=np.uint8)
        img_bgr = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
else:
    st.info("📷 Webcam capture coming soon - use Upload Image for now")

if img_bgr is not None:
    st.success("✅ Image loaded successfully")

    # Detect face
    with st.spinner("Detecting face..."):
        engine = get_engine()
        dets = engine.detect(img_bgr)

    if len(dets) == 0:
        st.error("❌ No face detected in image. Please upload an image with a clear face.")
    else:
        face = dets[0]
        kps = face.kps
        bbox = face.bbox.astype(int)
        det_score = float(face.score)

        st.success(f"✅ Face detected with confidence: {det_score:.3f}")

        # Perform alignment and compute all metrics
        aligned, M = align_face(img_bgr, kps)
        blur = laplacian_variance(aligned)
        pose = pose_score(kps)
        liveness, fft_spectrum = compute_fft_liveness(aligned)

        # Decompose affine matrix
        scale = float(np.sqrt(M[0,0]**2 + M[0,1]**2))
        angle = float(np.arctan2(M[1,0], M[0,0]) * 180 / np.pi)
        tx, ty = float(M[0,2]), float(M[1,2])

        # Display results
        st.markdown("---")
        st.markdown("### 📊 Analysis Results")

        # Two-column layout
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### 🖼️ Aligned Face (112×112 ArcFace Layout)")
            aligned_rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
            st.image(aligned_rgb, width=224, caption="Canonical alignment for embedding")

            st.markdown("#### 📏 Quality Metrics")

            # Blur score
            blur_status = "✅ Sharp" if blur >= 30.0 else "⚠️ Acceptable" if blur >= 15.0 else "❌ Blurry"
            st.metric("Blur Score (Laplacian Variance)", f"{blur:.1f}", delta=blur_status)

            # Pose score
            pose_status = "✅ Frontal" if pose >= 0.7 else "⚠️ Acceptable" if pose >= 0.45 else "❌ Profile"
            st.metric("Pose Score (Frontal-ness)", f"{pose:.3f}", delta=pose_status)

            # Detection score
            st.metric("Detection Confidence", f"{det_score:.3f}")

        with col2:
            st.markdown("#### 🌈 FFT Spectrum (2D Frequency Domain)")
            fft_rgb = cv2.cvtColor(fft_spectrum, cv2.COLOR_BGR2RGB)
            st.image(fft_rgb, width=224, caption="Log-magnitude spectrum (COLORMAP_INFERNO)")

            st.markdown("#### 🔬 Liveness Analysis")

            # Liveness score
            liveness_status = "✅ Real Face" if liveness >= 0.48 else "⚠️ Uncertain" if liveness >= 0.35 else "❌ Possible Spoof"
            st.metric("FFT Liveness Score", f"{liveness:.3f}", delta=liveness_status)

            st.caption("""
            **How it works:**
            - Real 3D faces: Natural mid-frequency texture from skin pores
            - Phone screens: Moiré interference spikes in high frequencies
            - Score = (mid_energy - 0.65 × high_energy) / total_energy
            """)

        st.markdown("---")
        st.markdown("### 🔢 Umeyama SVD Affine Transformation")

        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown("#### Transformation Matrix (2×3)")
            st.code(f"""
M = [{M[0,0]:9.4f}  {M[0,1]:9.4f} | {M[0,2]:9.2f}]
    [{M[1,0]:9.4f}  {M[1,1]:9.4f} | {M[1,2]:9.2f}]

Maps detected landmarks → canonical 112×112 layout
""")

        with col2:
            st.markdown("#### Decomposition")
            st.metric("Scale Factor", f"{scale:.4f}")
            st.metric("Rotation Angle", f"{angle:.2f}°")
            st.metric("Translation", f"({tx:.1f}, {ty:.1f}) pixels")

        st.markdown("---")
        st.markdown("### 🎯 Landmark Mapping")

        # Show original image with landmarks
        img_display = img_bgr.copy()
        cv2.rectangle(img_display, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)

        landmark_names = ["Left Eye", "Right Eye", "Nose Tip", "Left Mouth", "Right Mouth"]
        for i, (x, y) in enumerate(kps.astype(int)):
            cv2.circle(img_display, (x, y), 3, (0, 255, 255), -1)
            cv2.putText(img_display, str(i+1), (x+5, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### Original Image with Landmarks")
            st.image(cv2.cvtColor(img_display, cv2.COLOR_BGR2RGB), use_column_width=True)

        with col2:
            st.markdown("#### Landmark Coordinates")
            landmark_df = {
                "Point": landmark_names,
                "Original X": kps[:, 0].astype(int),
                "Original Y": kps[:, 1].astype(int),
                "Canonical X": ARCFACE_REF[:, 0].astype(int),
                "Canonical Y": ARCFACE_REF[:, 1].astype(int)
            }
            st.dataframe(landmark_df, hide_index=True)

        st.markdown("---")
        st.markdown("### 📐 Mathematical Details")

        with st.expander("🔍 SVD-based Similarity Transform (Umeyama 1991)"):
            st.markdown("""
            Solves for optimal scale `c`, rotation `R`, and translation `t`:

            **min Σ ||dst_i - (c·R·src_i + t)||²**

            Steps:
            1. Center point sets: P = src - μ_src, Q = dst - μ_dst
            2. Covariance: Σ = (1/n)·Q^T·P
            3. SVD: Σ = U·D·V^T
            4. Rotation: R = U·S·V^T where S = diag(1, det(U·V^T))
            5. Scale: c = tr(D·S) / var(P)
            6. Translation: t = μ_dst - c·R·μ_src

            **Why SVD?** Least-squares optimal under point noise, handles reflections.
            """)

        with st.expander("🌊 2D FFT Frequency-Domain Analysis"):
            st.markdown("""
            **Processing Pipeline:**
            1. Convert to grayscale float32
            2. Apply 2D Hann window: `hann_h[:, None] @ hann_w[None, :]`
            3. Compute 2D DFT: `fft2(windowed_signal)`
            4. Shift zero-frequency to center: `fftshift`
            5. Log-magnitude spectrum: `log1p(|fft_shift|)`

            **Frequency Bands:**
            - **Mid-frequency (r ∈ [8, 28])**: Natural 3D skin texture
            - **High-frequency (r > 28)**: OLED/LCD moiré interference
            - **Total AC (r ≥ 4)**: All non-DC components

            **Liveness Score:**
            ```
            score = clip(((E_mid - 0.65·E_high) / E_total) · 1.15, 0, 1)
            ```

            Real faces: Higher mid/total ratio (skin texture dominates)
            Spoofs: High-frequency spikes from screen pixels
            """)

        with st.expander("📊 Quality Gates in Pipeline"):
            from config import DEFAULT_SETTINGS
            s = DEFAULT_SETTINGS

            st.markdown(f"""
            **Quality Thresholds (from config.py):**
            - Detection score: ≥ {s.min_det_score:.2f}
            - Face size: ≥ {s.min_face_px} px
            - Blur (live): ≥ {s.min_blur_var:.1f}
            - Blur (enroll): ≥ {s.enroll_min_blur_var:.1f}
            - Pose: ≥ {s.min_pose_score:.2f}
            - FFT Liveness: ≥ {s.min_fft_liveness_score:.2f} (if enabled)

            **This face:**
            - Detection: {det_score:.3f} {'✅' if det_score >= s.min_det_score else '❌'}
            - Blur: {blur:.1f} {'✅' if blur >= s.min_blur_var else '❌'}
            - Pose: {pose:.3f} {'✅' if pose >= s.min_pose_score else '❌'}
            - Liveness: {liveness:.3f} {'✅' if liveness >= s.min_fft_liveness_score else '❌'}
            """)

        st.markdown("---")
        st.markdown("### 💾 Export Data")

        # Export button for all metrics
        export_data = {
            "detection_score": det_score,
            "blur_score": blur,
            "pose_score": pose,
            "liveness_score": liveness,
            "affine_matrix": M.tolist(),
            "scale": scale,
            "rotation_deg": angle,
            "translation": [tx, ty],
            "landmarks_original": kps.tolist(),
            "landmarks_canonical": ARCFACE_REF.tolist()
        }

        import json
        json_str = json.dumps(export_data, indent=2)

        st.download_button(
            "⬇ Download All Metrics (JSON)",
            json_str,
            file_name="face_math_metrics.json",
            mime="application/json"
        )

else:
    st.info("👆 Upload an image to begin mathematical analysis")

    st.markdown("---")
    st.markdown("### 📚 About This Inspector")

    st.markdown("""
    This tool demonstrates the mathematical foundations of the face recognition pipeline:

    1. **Umeyama SVD Alignment**: Least-squares similarity transform mapping detected landmarks to canonical layout
    2. **2D FFT Liveness**: Frequency-domain anti-spoofing using mid vs. high-frequency energy ratios
    3. **Quality Metrics**: Laplacian variance (blur), landmark-based pose estimation
    4. **Visualization**: Inferno heatmap of log-magnitude spectrum

    **Use Cases:**
    - Viva demonstrations of mathematical concepts
    - Interactive debugging of quality gates
    - Understanding why certain faces pass/fail
    - Educational demonstrations of computer vision mathematics

    **Note:** This is a diagnostic tool. Production recognition uses the full pipeline with
    Kalman tracking, ByteTrack association, and FAISS HNSW vector search.
    """)

st.sidebar.markdown("---")
st.sidebar.markdown("**Math Inspector v2.0**")
st.sidebar.caption(f"Search method: {get_store().load_gallery().search_method}")
