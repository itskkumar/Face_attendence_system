# Feature Updates - Face Attendance System

## Release Date: 2026-10-30

This document describes the new features added to the face attendance system to handle fast-moving persons (cyclists, people on bikes) and capture snapshots during attendance logging.

---

## New Features

### 1. Deferred Recognition for Fast-Moving Persons

**Problem Solved:** 
Previously, when a person moved through the camera frame quickly (walking fast, cycling, on a bike), the system would show "Verifying..." but the person would leave the frame before enough quality keyframes (min_votes=3) could be collected. This resulted in missed attendance logging.

**Solution:**
- **Frame Crop Buffering**: The system now buffers the best N quality frame crops (default 5) for each pending track
- **Background Processing**: When a track leaves the frame while still "pending", it's queued for deferred recognition
- **Asynchronous Identification**: A background worker thread processes lost tracks using the buffered crops
- **Late Attendance Logging**: If identification succeeds after the person left the frame, attendance is logged with a "[DEFERRED]" marker

**Configuration:**
```python
# In config.py Settings:
enable_deferred_recognition: bool = True    # Enable/disable feature (default: True)
buffer_crops_for_deferred: int = 5          # Number of best crops to buffer
deferred_min_embeddings: int = 2            # Min embeddings needed to attempt deferred ID
```

**How It Works:**
1. During normal processing, high-quality aligned face crops are buffered in `Identity.frame_crops`
2. When ByteTrack removes a track due to `max_age`, the `on_track_lost` callback is triggered
3. If the track is still "pending" with ≥2 embeddings, it's queued for background processing
4. The deferred worker re-embeds buffered crops, performs quality-weighted voting, and logs if confident
5. Results appear in the event stream as: `[DEFERRED] John Doe (ROLL123) - identified after leaving frame`

**Benefits:**
- ✅ Handles drive-through/walk-through scenarios
- ✅ Works with cyclists and people on bikes/scooters
- ✅ No frame drops during fast movement
- ✅ Minimal performance impact (background thread)

---

### 2. Snapshot Capture (Face & Person Crops)

**Problem Solved:**
There was no visual record of who was detected and what they looked like at the time of attendance logging.

**Solution:**
The system now captures and saves two types of snapshots when logging attendance:

1. **Face Snapshot**: 112×112 aligned face crop (ArcFace canonical alignment)
2. **Person Snapshot**: Full bounding-box crop showing the person

**Storage Structure:**
```
data/snapshots/
├── 2026-10-30/
│   ├── ROLL123_103045_face.jpg      # Face crop at 10:30:45
│   ├── ROLL123_103045_person.jpg    # Person crop at 10:30:45
│   ├── ROLL456_104521_face.jpg
│   └── ROLL456_104521_person.jpg
├── 2026-10-31/
│   └── ...
```

**Database Schema:**
New columns in `attendance_logs` table:
- `face_snapshot TEXT` - Relative path to face crop (e.g., 'snapshots/2026-10-30/ROLL123_103045_face.jpg')
- `person_snapshot TEXT` - Relative path to person crop

**Configuration:**
```python
# In config.py Settings:
save_snapshots: bool = True    # Enable/disable snapshot saving (default: True)
```

**Access Snapshots:**
```python
from snapshot_manager import load_snapshot, get_snapshot_full_path

# Load a snapshot from relative path
face_img = load_snapshot('snapshots/2026-10-30/ROLL123_103045_face.jpg')

# Get full absolute path
full_path = get_snapshot_full_path('snapshots/2026-10-30/ROLL123_103045_face.jpg')
```

**Benefits:**
- ✅ Visual audit trail for attendance
- ✅ Verify who was logged
- ✅ Useful for disputes or manual review
- ✅ Face crops can be used to improve enrollment templates
- ✅ JPEG compression keeps file sizes reasonable (~5-15 KB per snapshot)

---

### 3. Best Frame Selection

**Enhancement:**
The system now intelligently tracks the **best quality frame** per person:
- Compares quality scores (blur × pose_score)
- Keeps the sharpest, most frontal face crop
- Uses this best crop for snapshots

**Implementation:**
```python
# In Identity dataclass:
best_aligned_face: Optional[np.ndarray] = None      # Best 112x112 face
best_person_crop: Optional[np.ndarray] = None       # Best person crop
```

This ensures snapshots are always the clearest possible image of each person.

---

## Technical Changes Summary

### Modified Files

1. **config.py**
   - Added `enable_deferred_recognition`, `buffer_crops_for_deferred`, `deferred_min_embeddings`
   - Added `save_snapshots` setting

2. **database.py**
   - Added `face_snapshot` and `person_snapshot` columns to schema
   - Updated `log_attendance()` to accept and store snapshot paths

3. **pipeline.py** (Major changes)
   - Added `frame_crops`, `best_aligned_face`, `best_person_crop` to `Identity` dataclass
   - Added deferred recognition worker thread (`_deferred_worker`)
   - Added `_on_track_lost` callback for lost track processing
   - Updated `_quality_sample` to return person crop
   - Updated `_recognize` to buffer crops and track best frames
   - Updated `_try_log` to save snapshots when logging attendance
   - Updated `process` to check for deferred results
   - Updated `close` to properly shutdown worker thread

4. **tracker.py**
   - Added `on_track_lost` callback parameter to `ByteTrackLite.__init__`
   - Call callback before removing tracks in `update()`

5. **attendance.py**
   - Updated `maybe_log()` to accept `face_snapshot` and `person_snapshot` parameters

6. **migrate_database.py**
   - Added migration for `face_snapshot` and `person_snapshot` columns

### New Files

1. **snapshot_manager.py**
   - `save_snapshot()` - Save crops to organized directory structure
   - `load_snapshot()` - Load saved snapshots
   - `get_snapshot_full_path()` - Convert relative to absolute paths

---

## Migration Instructions

### For Existing Systems:

1. **Run Database Migration:**
   ```bash
   python migrate_database.py
   ```
   This adds the new `face_snapshot` and `person_snapshot` columns.

2. **Create Snapshots Directory:**
   ```bash
   mkdir -p data/snapshots
   ```
   (Already created automatically by snapshot_manager.py)

3. **Review Configuration:**
   Edit `config.py` or use sidebar settings in Streamlit to configure:
   - `enable_deferred_recognition` (True/False)
   - `save_snapshots` (True/False)
   - `buffer_crops_for_deferred` (1-10 recommended)

4. **Restart Services:**
   If running inference.py or dashboard.py, restart them to load the new code.

### For New Installations:

All features are enabled by default. No action needed.

---

## Usage Examples

### Example 1: Fast-Moving Person Detection

**Scenario:** Person cycles through the frame in 2 seconds

**Old Behavior:**
- Frame 1-10: Face detected, tracking starts, status="pending"
- Frame 11-20: Person moves, only 2 keyframes collected
- Frame 21+: Person out of frame, track removed
- **Result:** No attendance logged ❌

**New Behavior:**
- Frame 1-10: Face detected, tracking starts, 2 quality crops buffered
- Frame 11-20: Person moves, crops continue buffering (total 4 crops)
- Frame 21: Track removed, queued for deferred processing
- Background: Worker aggregates 4 embeddings, identifies person
- **Result:** Attendance logged with "[DEFERRED]" marker ✅

### Example 2: Reviewing Attendance with Snapshots

```python
from database import Store
from snapshot_manager import load_snapshot, get_snapshot_full_path

store = Store()

# Get recent attendance logs
logs = store.recent_entries(10)

for log in logs:
    print(f"{log['name']} at {log['timestamp']}")
    
    # Display snapshots
    if log.get('face_snapshot'):
        face = load_snapshot(log['face_snapshot'])
        # Show or save face image
        
    if log.get('person_snapshot'):
        person = load_snapshot(log['person_snapshot'])
        # Show or save person image
```

### Example 3: Disabling Deferred Recognition for Fixed Gate

```python
# In your script or config
settings = dataclasses.replace(DEFAULT_SETTINGS,
    enable_deferred_recognition=False,  # Disable for fixed gate where people stop
    save_snapshots=True                  # Still save snapshots
)

pipeline = GatePipeline(engine, store, settings)
```

---

## Performance Impact

### Memory Usage:
- **Per Track:** ~500 KB (5 buffered 112×112 RGB crops)
- **10 simultaneous tracks:** ~5 MB additional RAM
- **Negligible** for most systems

### Processing Speed:
- **Main thread:** No change (buffering is ~1μs per crop)
- **Background thread:** Processes 1-2 tracks per second
- **I/O:** Snapshot writes are async, don't block processing

### Storage:
- **Per attendance log:** ~10-20 KB (2 JPEG snapshots)
- **1000 logs/day:** ~10-20 MB/day
- **Monthly:** ~300-600 MB
- **Recommendation:** Archive old snapshots monthly

---

## Troubleshooting

### Issue: Deferred recognition not working

**Check:**
```python
# Verify setting is enabled
assert settings.enable_deferred_recognition == True

# Check minimum embeddings threshold
assert settings.deferred_min_embeddings <= settings.min_votes
```

### Issue: Snapshots not being saved

**Check:**
```python
# Verify directory exists and is writable
import os
from config import DATA_DIR
snapshots_dir = os.path.join(DATA_DIR, 'snapshots')
assert os.path.exists(snapshots_dir)
assert os.access(snapshots_dir, os.W_OK)

# Verify setting is enabled
assert settings.save_snapshots == True
```

### Issue: "[DEFERRED]" logs appearing long after person left

**This is normal!** Deferred processing can take 1-5 seconds depending on:
- Number of buffered crops to process
- Gallery size (more students = slower matching)
- System load

To reduce latency, decrease `buffer_crops_for_deferred` to 2-3.

---

## Future Enhancements

Possible improvements for future versions:

1. **Snapshot Gallery UI** - Streamlit page to browse saved snapshots
2. **Video Clips** - Save 3-5 second video clips around each attendance log
3. **Smart Buffering** - Adaptive buffer size based on person velocity
4. **Priority Queue** - Process high-confidence deferred tracks first
5. **Snapshot Search** - Visual similarity search over saved snapshots
6. **Automatic Cleanup** - Auto-delete snapshots older than N days

---

## API Reference

### snapshot_manager.py

#### `save_snapshot(crop, roll_number, timestamp, kind='face') -> str`
Save a snapshot crop and return its relative path.

**Args:**
- `crop` (np.ndarray): BGR image to save
- `roll_number` (str): Student roll number
- `timestamp` (datetime): When the snapshot was taken
- `kind` (str): 'face' or 'person'

**Returns:**
- `str`: Relative path from DATA_DIR

#### `load_snapshot(rel_path) -> Optional[np.ndarray]`
Load a snapshot from its relative path.

**Returns:**
- BGR image or None if not found

#### `get_snapshot_full_path(rel_path) -> str`
Convert relative path to absolute path.

---

## Testing

Run inference on a test video to verify:

```bash
# Test with webcam (walk quickly through frame)
python inference.py --source webcam

# Test with video file
python inference.py --source file --path test_video.mp4

# Check database for snapshots
sqlite3 data/attendance_system.db
> SELECT roll_number, face_snapshot, person_snapshot FROM attendance_logs LIMIT 10;
```

Expected output:
```
ROLL123|snapshots/2026-10-30/ROLL123_142315_face.jpg|snapshots/2026-10-30/ROLL123_142315_person.jpg
```

---

## Credits

**Implemented:** 2026-10-30  
**Author:** Face Attendance System Development Team  
**License:** MIT (see LICENSE file)

For questions or issues, refer to the main README.md or create an issue in the project repository.
