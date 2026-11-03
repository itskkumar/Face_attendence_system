"""
snapshot_manager.py - save face and person crops for attendance logging.

Snapshots are organized as:
    data/snapshots/{date}/{roll_number}_{timestamp}_{face|person}.jpg

face:   112x112 aligned ArcFace crop
person: bounding-box crop of the full person
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

from config import DATA_DIR


SNAPSHOTS_DIR = os.path.join(DATA_DIR, "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def save_snapshot(crop: np.ndarray, roll_number: str, timestamp: datetime,
                  kind: str = "face") -> str:
    """
    Save a snapshot crop and return its relative path.

    Args:
        crop: BGR image to save
        roll_number: student roll number
        timestamp: when the snapshot was taken
        kind: 'face' or 'person'

    Returns:
        Relative path from DATA_DIR (e.g., 'snapshots/2026-10-30/ROLL123_103045_face.jpg')
    """
    date_str = timestamp.strftime("%Y-%m-%d")
    date_dir = os.path.join(SNAPSHOTS_DIR, date_str)
    os.makedirs(date_dir, exist_ok=True)

    time_str = timestamp.strftime("%H%M%S")
    filename = f"{roll_number}_{time_str}_{kind}.jpg"
    full_path = os.path.join(date_dir, filename)

    # Save with reasonable quality
    cv2.imwrite(full_path, crop, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # Return relative path from DATA_DIR
    rel_path = os.path.relpath(full_path, DATA_DIR)
    return rel_path


def load_snapshot(rel_path: str) -> Optional[np.ndarray]:
    """Load a snapshot from its relative path."""
    full_path = os.path.join(DATA_DIR, rel_path)
    if not os.path.exists(full_path):
        return None
    return cv2.imread(full_path)


def get_snapshot_full_path(rel_path: str) -> str:
    """Convert relative path to absolute path."""
    return os.path.join(DATA_DIR, rel_path)
