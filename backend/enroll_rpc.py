"""
backend/enroll_rpc.py - enrollment executed INSIDE the gate worker process (the only process that owns
a FaceEngine and a PAD session). The API forwards camera samples / photos here over the worker link.
`enrollment_core.analyze_face_for_enrollment` is used unchanged. Embeddings never leave this process.

PAD rules (spec 4.7)
  * live camera sample: when PAD is READY the sample must be LIVE; a SPOOF sample is always refused
  * PAD not configured / errored: the sample is accepted but the session is recorded as
    "liveness not verified" (or refused with ENROLL_REQUIRE_LIVENESS=1)
  * uploaded photos: no liveness is possible; admin-only (API), audit-logged as "liveness not verified"
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Dict, List

import cv2
import numpy as np

import antispoof
from enrollment_core import analyze_face_for_enrollment

TARGET_SAMPLES = 5
SESSION_TTL = 15 * 60


class EnrollError(Exception):
    pass


def _decode(jpeg: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise EnrollError("Not a valid image.")
    return img


class EnrollmentService:
    def __init__(self, store, get_engine, get_pad, settings_getter, require_liveness: bool = False):
        self.store, self.get_engine, self.get_pad, self.settings = store, get_engine, get_pad, settings_getter
        self.require_liveness = require_liveness
        self.sessions: Dict[str, dict] = {}

    def _gc(self):
        now = time.time()
        for k in [k for k, v in self.sessions.items() if now - v["t"] > SESSION_TTL]:
            del self.sessions[k]

    def status(self) -> dict:
        pad = self.get_pad().health()
        return {"engine_ready": self.get_engine() is not None, "pad": pad, "liveness_mode": self.settings().liveness_mode,
                "require_liveness": self.require_liveness}

    def open(self, meta: dict) -> dict:
        self._gc()
        roll, name = (meta.get("roll_number") or "").strip().upper(), (meta.get("name") or "").strip()
        if not roll or not name:
            raise EnrollError("Name and roll number are required.")
        sid = secrets.token_urlsafe(12)
        self.sessions[sid] = {"meta": dict(meta, roll_number=roll, name=name), "samples": [], "verified": [], "t": time.time()}
        return {"session_id": sid, "target_samples": TARGET_SAMPLES}

    def _session(self, sid: str) -> dict:
        s = self.sessions.get(sid)
        if not s:
            raise EnrollError("Unknown or expired enrollment session.")
        s["t"] = time.time()
        return s

    def sample(self, sid: str, jpeg: bytes) -> dict:
        s = self._session(sid)
        engine, pad = self.get_engine(), self.get_pad()
        health = pad.health()
        ready = health["state"] == "READY"
        if not ready and self.require_liveness:
            raise EnrollError("Anti-spoofing is not configured and ENROLL_REQUIRE_LIVENESS is set.")
        frame = _decode(jpeg)
        sample, reason = analyze_face_for_enrollment(engine, frame, self.settings())
        if sample is None:
            return {"accepted": False, "reason": reason, "pad_state": None, "pad_real_prob": None, "count": len(s["samples"]), "target": TARGET_SAMPLES}
        pad_state, real = None, None
        if ready:
            dets = [d for d in engine.detect(frame) if d.kps is not None]
            best = max(dets, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
            res = pad.observe(frame, best.bbox)
            pad_state, real = res.state, res.real_prob
            if res.state != antispoof.LIVE:
                why = "Possible spoof (photo/screen) - sample refused" if res.state == antispoof.SPOOF else "Liveness not confirmed - hold still and face the camera"
                return {"accepted": False, "reason": why, "pad_state": pad_state, "pad_real_prob": real, "count": len(s["samples"]), "target": TARGET_SAMPLES}
        s["samples"].append(sample)
        s["verified"].append(ready)
        return {"accepted": True, "reason": "", "pad_state": pad_state, "pad_real_prob": real, "count": len(s["samples"]), "target": TARGET_SAMPLES}

    def finish(self, sid: str) -> dict:
        s = self._session(sid)
        if not s["samples"]:
            raise EnrollError("No accepted samples yet.")
        return self._save(s["meta"], s["samples"], all(s["verified"]), s["meta"].get("mode", "replace"), sid)

    def cancel(self, sid: str) -> dict:
        self.sessions.pop(sid, None)
        return {"ok": True}

    def _save(self, meta: dict, samples: list, verified: bool, mode: str, sid: str = None) -> dict:
        embs = [x.embedding for x in samples]
        dup = self.store.find_duplicate_identity(embs, meta["roll_number"])
        if dup:
            raise EnrollError(f"Refused: this face already matches {dup[1]} ({dup[0]}) with similarity {dup[2]:.2f}.")
        _, n = self.store.add_student(meta["roll_number"], meta["name"], embs, [x.quality for x in samples], mode=mode,
                                      email=meta.get("email", ""), phone=meta.get("phone", ""),
                                      department=meta.get("department", ""), batch=meta.get("batch", ""),
                                      expected_time=meta.get("expected_time", ""))
        if sid:
            self.sessions.pop(sid, None)
        return {"ok": True, "templates": n, "liveness_verified": bool(verified)}

    def photos(self, meta: dict, files: List[bytes]) -> dict:
        roll, name = (meta.get("roll_number") or "").strip().upper(), (meta.get("name") or "").strip()
        if not roll or not name:
            raise EnrollError("Name and roll number are required.")
        if not 1 <= len(files) <= 8:
            raise EnrollError("Upload between 1 and 8 photos.")
        engine, samples, rejected = self.get_engine(), [], []
        for i, raw in enumerate(files):
            try:
                smp, why = analyze_face_for_enrollment(engine, _decode(raw), self.settings())
            except EnrollError as exc:
                smp, why = None, str(exc)
            if smp is None:
                rejected.append({"filename": (meta.get("filenames") or [])[i] if i < len(meta.get("filenames") or []) else f"photo {i + 1}", "reason": why})
            else:
                samples.append(smp)
        if not samples:
            raise EnrollError("No usable face in any photo: " + "; ".join(r["reason"] for r in rejected))
        out = self._save(dict(meta, roll_number=roll, name=name), samples, False, meta.get("mode", "replace"))
        out["rejected"], out["liveness_verified"] = rejected, False
        return out
