# Mathematical & Systems Upgrades Implementation Status

**Date:** 2026-11-03  
**Target:** Face Attendance v2 on MacBook Air M4

## 🎯 Four Features to Implement

### ✅ Feature 1: Passive 2D FFT Frequency-Domain Anti-Spoofing
**Status:** 90% Complete

**Completed:**
- ✅ Added `enable_fft_liveness` and `min_fft_liveness_score` to `config.py`
- ✅ Implemented `compute_fft_liveness()` in `vision_math.py` with:
  - 2D Hann window to eliminate edge spectral leakage
  - 2D DFT with fftshift and log-magnitude spectrum
  - Radial frequency band energies (mid 8-28, high >28, total >=4)
  - Liveness score formula: `((mid - 0.65*high) / total) * 1.15`
  - COLORMAP_INFERNO spectrum visualization (112x112x3)
- ✅ Updated `pipeline.py` imports to include `compute_fft_liveness`

**TODO:**
- [ ] Wire into pipeline quality gate (see implementation below)
- [ ] Add unit tests to `tests/test_vision_math.py`

### ✅ Feature 2: Kinematic Mahalanobis Distance in ByteTrack  
**Status:** 100% Complete

**Completed:**
- ✅ Added `mahalanobis_distance()` method to `Track` class in `tracker.py`
  - Computes innovation residual `y = z - H @ x`
  - Computes innovation covariance `S = H @ P @ H.T + R`
  - Returns `sqrt(y^T @ inv(S) @ y)`
- ✅ Enhanced `_associate()` to accept `use_hybrid_cost` parameter
  - Stage-1: `0.75 * (1 - IoU) + 0.25 * normalized_mahalanobis`
  - Stage-2: Pure IoU (unchanged for occlusion recovery)
- ✅ Updated `update()` to use hybrid cost for high-confidence matches

**Tests Needed:**
- [ ] Add unit tests to `tests/test_tracker.py`

### ✅ Feature 3: O(log N) FAISS HNSW Vector Indexing
**Status:** 100% Complete

**Completed:**
- ✅ Added `faiss-cpu>=1.8.0` to `requirements.txt`
- ✅ Added FAISS config params to `config.py`:
  - `enable_faiss_hnsw`, `faiss_hnsw_m`, `faiss_ef_construction`, `faiss_ef_search`
- ✅ Updated `database.py`:
  - Import FAISS with clean fallback
  - `Gallery.__init__` accepts `use_faiss` parameter
  - `_build_faiss_index()` creates HNSW with METRIC_INNER_PRODUCT
  - `match()` uses FAISS search if available, otherwise NumPy fallback
  - `search_method` property shows "FAISS HNSW O(log N)" or "NumPy O(N)"
- ✅ Updated `load_gallery()` to enable FAISS when configured

**Tests Needed:**
- [ ] Add unit tests to `tests/test_database.py`

### ⏳ Feature 4: Mathematical Pipeline Inspector Page
**Status:** 0% Complete

**TODO:**
- [ ] Add thread-safe diagnostics storage to `pipeline.py`
- [ ] Create `pages/3_Math_Inspector.py` with:
  - Track ID, aligned face (112x112 RGB)
  - FFT spectrum (Inferno heatmap)
  - Affine matrix (2x3 Umeyama SVD)
  - Blur score, pose score, liveness score
  - Kalman state vector display
  - Test image upload/capture for interactive inspection
- [ ] Use shared styling from `ui_common.py`

---

## 📝 Code Snippets for Completion

### 1. Pipeline Integration for FFT Liveness

Add to `pipeline.py` in the `_recognize_one_track()` method after alignment:

```python
# Around line 250-270 where quality gates are checked
aligned, M = align_face(frame, kps)
blur = laplacian_variance(aligned)
pose = pose_score(kps)

# NEW: FFT Liveness Check
liveness_score = 1.0
fft_spectrum = None
if self.s.enable_fft_liveness:
    liveness_score, fft_spectrum = compute_fft_liveness(aligned)
    if liveness_score < self.s.min_fft_liveness_score:
        ident.hint = f"spoof ({liveness_score:.2f})"
        ident.spoof_votes += 1
        if ident.spoof_votes >= 3:
            ident.status = "spoof"
        return  # Skip this face
```

### 2. Unit Tests for `test_vision_math.py`

```python
def test_compute_fft_liveness_output_range():
    """FFT liveness score must be in [0, 1] range."""
    rng = np.random.default_rng(42)
    aligned = rng.integers(0, 255, (112, 112, 3), dtype=np.uint8)
    score, spectrum = compute_fft_liveness(aligned)
    assert 0.0 <= score <= 1.0
    assert spectrum.shape == (112, 112, 3)
    assert spectrum.dtype == np.uint8

def test_compute_fft_liveness_spectrum_colormap():
    """Spectrum visualization should be valid uint8 image."""
    aligned = np.random.default_rng(1).integers(0, 255, (112, 112, 3), dtype=np.uint8)
    _, spectrum = compute_fft_liveness(aligned)
    assert spectrum.min() >= 0 and spectrum.max() <= 255
```

### 3. Unit Tests for `test_tracker.py`

```python
def test_mahalanobis_distance():
    """Mahalanobis distance returns non-negative values."""
    from tracker import Track, Detection, KalmanFilterXYAH
    kf = KalmanFilterXYAH()
    det = Detection(bbox=np.array([100, 100, 200, 200]), kps=None, score=0.9)
    track = Track(1, det, kf, frame_idx=0)
    
    # Same bbox should give low distance
    dist_same = track.mahalanobis_distance(det.bbox)
    assert dist_same >= 0.0
    assert dist_same < 5.0
    
    # Far bbox should give high distance
    far_bbox = np.array([500, 500, 600, 600])
    dist_far = track.mahalanobis_distance(far_bbox)
    assert dist_far > dist_same

def test_hybrid_cost_prevents_id_switching():
    """Hybrid cost matrix reduces ID switches during fast motion."""
    # TODO: Implement integration test with crossing tracks
    pass
```

### 4. Unit Tests for `test_database.py`

```python
def test_faiss_index_builds_successfully(tmp_store):
    """FAISS HNSW index builds when enabled and available."""
    if not FAISS_AVAILABLE:
        pytest.skip("FAISS not installed")
    
    embs = [np.random.randn(512).astype(np.float32) for _ in range(10)]
    tmp_store.add_student("TEST001", "Test Student", embs)
    
    gallery = tmp_store.load_gallery()
    if gallery.use_faiss:
        assert gallery.search_method == "FAISS HNSW O(log N)"
        assert gallery.faiss_index is not None
        assert gallery.faiss_index.ntotal == 11  # 10 templates + 1 centroid

def test_faiss_search_matches_numpy_search(tmp_store):
    """FAISS approximate search returns same student as exact NumPy search."""
    if not FAISS_AVAILABLE:
        pytest.skip("FAISS not installed")
    
    rng = np.random.default_rng(42)
    embs = [rng.randn(512).astype(np.float32) for _ in range(5)]
    tmp_store.add_student("TEST001", "Student A", embs[:2])
    tmp_store.add_student("TEST002", "Student B", embs[2:])
    
    query = embs[0] + rng.randn(512).astype(np.float32) * 0.1
    
    # Test with FAISS
    gallery_faiss = tmp_store.load_gallery()
    match_faiss = gallery_faiss.match(query)
    
    # Test with NumPy (force)
    gallery_numpy = tmp_store.load_gallery()
    gallery_numpy.use_faiss = False
    match_numpy = gallery_numpy.match(query)
    
    assert match_faiss.student.roll_number == match_numpy.student.roll_number
    assert abs(match_faiss.similarity - match_numpy.similarity) < 0.05
```

### 5. Math Inspector Page Template

```python
# pages/3_Math_Inspector.py
import streamlit as st
import numpy as np
import cv2
from vision_math import compute_fft_liveness, align_face, laplacian_variance, pose_score
from ui_common import get_engine

st.set_page_config(page_title="Math Inspector", page_icon="🔬", layout="wide")

st.title("🔬 Mathematical Pipeline Inspector")

# Upload test image
uploaded = st.file_uploader("Upload test face image", type=['jpg', 'png', 'jpeg'])

if uploaded:
    file_bytes = np.asarray(bytearray(uploaded.read()), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    
    engine = get_engine()
    faces = engine.get_det(img, max_num=1)
    
    if len(faces) > 0:
        kps = faces[0].kps
        aligned, M = align_face(img, kps)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Aligned Face (112x112)")
            st.image(cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB))
            
            st.subheader("Quality Metrics")
            blur = laplacian_variance(aligned)
            pose = pose_score(kps)
            st.metric("Blur Score", f"{blur:.1f}")
            st.metric("Pose Score", f"{pose:.3f}")
        
        with col2:
            st.subheader("FFT Spectrum (COLORMAP_INFERNO)")
            liveness, spectrum = compute_fft_liveness(aligned)
            st.image(cv2.cvtColor(spectrum, cv2.COLOR_BGR2RGB))
            st.metric("Liveness Score", f"{liveness:.3f}")
        
        st.subheader("Umeyama SVD Affine Matrix (2x3)")
        st.code(f"M = \n{M}")
        
        st.subheader("Transformation Details")
        scale = np.sqrt(M[0,0]**2 + M[0,1]**2)
        angle = np.arctan2(M[1,0], M[0,0]) * 180 / np.pi
        st.write(f"- Scale: {scale:.3f}")
        st.write(f"- Rotation: {angle:.1f}°")
        st.write(f"- Translation: ({M[0,2]:.1f}, {M[1,2]:.1f})")
```

---

## ⚡ Quick Completion Commands

```bash
# Install FAISS (optional, with fallback)
pip install faiss-cpu>=1.8.0

# Run specific test suites
pytest tests/test_vision_math.py -v
pytest tests/test_tracker.py -v
pytest tests/test_database.py -v
pytest tests/test_pipeline_logic.py -v

# Run all tests
pytest tests/ -v

# Run benchmark
python benchmark.py
```

---

## 🎓 Viva Demonstration Points

1. **FFT Liveness:** Show spectrum heatmap differentiating real vs. phone screen
2. **Mahalanobis:** Demonstrate ID stability when students cross paths
3. **FAISS HNSW:** Show `gallery.search_method` reporting O(log N) vs O(N)
4. **Math Inspector:** Interactive SVD matrix, Kalman state vector display

---

## ✅ Testing Checklist

- [ ] `test_compute_fft_liveness_output_range()` passes
- [ ] `test_compute_fft_liveness_spectrum_colormap()` passes
- [ ] `test_mahalanobis_distance()` passes
- [ ] `test_hybrid_cost_prevents_id_switching()` passes (integration)
- [ ] `test_faiss_index_builds_successfully()` passes
- [ ] `test_faiss_search_matches_numpy_search()` passes
- [ ] `pytest tests/ -v` shows 100% pass rate
- [ ] `python benchmark.py` runs without errors
- [ ] Math Inspector page renders correctly

---

**Status:** Features 1-3 core implementation complete. Need to add tests and Feature 4 (Math Inspector page).
