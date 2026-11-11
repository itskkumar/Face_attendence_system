"""antispoof.py unit tests. Anything using a fake ONNX session is SIMULATED (no real weights are
bundled); the real-model test is skipped with a clear message when the weights are absent."""
import hashlib
import json
import os

import numpy as np
import pytest

import antispoof as A
from config import ANTISPOOFING_MODEL_DIR


# ---------------------------------------------------------------- preprocessing (locked)
def test_preprocess_shape_dtype_range_and_channel_order():
    img = np.zeros((480, 640, 3), np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = 10, 120, 250            # B, G, R planes are distinct
    x = A.preprocess(img, (200, 100, 320, 250), scale=2.7)
    assert x.shape == (1, 3, 80, 80) and x.dtype == np.float32
    assert x.max() == 250.0 and x.min() == 10.0                    # 0..255 range, NOT divided by 255
    assert np.all(x[0, 0] == 10) and np.all(x[0, 1] == 120) and np.all(x[0, 2] == 250)   # BGR order kept
    assert x.flags["C_CONTIGUOUS"]


def test_expand_bbox_shifts_instead_of_squashing_at_frame_edge():
    # face in the top-left corner: the expanded box must keep its size and slide inside the frame
    l, t, r, b = A.expand_bbox(640, 480, (5, 5, 100, 100), 2.7)
    assert (l, t) == (0, 0) and (r - l) == (b - t) and (r - l) >= 260
    # a centred face keeps scale * size and the same centre
    l, t, r, b = A.expand_bbox(1280, 960, (500, 400, 100, 100), 2.7)
    assert abs((r - l) - 270) <= 1 and abs((l + r) / 2 - 550) <= 1


def test_expand_bbox_never_leaves_frame():
    for box in [(600, 440, 40, 40), (0, 0, 640, 480), (300, 0, 50, 80)]:
        l, t, r, b = A.expand_bbox(640, 480, box, 4.0)
        assert 0 <= l <= r <= 639 and 0 <= t <= b <= 479


def test_degenerate_box_rejected():
    with pytest.raises(ValueError):
        A.preprocess(np.zeros((100, 100, 3), np.uint8), (10, 10, 11, 11), 2.7)


# ---------------------------------------------------------------- temporal decision
KW = dict(min_obs=3, real_threshold=0.7, spoof_threshold=0.7)


def test_decide_needs_min_observations():
    assert A.decide_pad([0.99, 0.99], **KW)[0] == A.UNCERTAIN
    assert A.decide_pad([], **KW)[0] == A.UNCERTAIN


def test_decide_live_spoof_and_mixed():
    assert A.decide_pad([0.9, 0.95, 0.92], **KW)[0] == A.LIVE
    assert A.decide_pad([0.05, 0.1, 0.02, 0.04], **KW)[0] == A.SPOOF
    assert A.decide_pad([0.9, 0.1, 0.9, 0.1, 0.5], **KW)[0] == A.UNCERTAIN
    assert A.decide_pad([0.95, 0.95, 0.2, 0.2, 0.2], **KW)[0] == A.UNCERTAIN     # one good streak is not enough


def test_decide_high_mean_but_few_individual_passes_is_not_live():
    # mean 0.74 >= 0.7 but only 1 of 5 observations clears the threshold
    assert A.decide_pad([0.99, 0.69, 0.69, 0.69, 0.69], **KW)[0] == A.UNCERTAIN


# ---------------------------------------------------------------- provider states
def test_null_pad_is_not_configured_never_live():
    r = A.NullPAD().observe(np.zeros((10, 10, 3), np.uint8), (0, 0, 5, 5))
    assert r.state == A.NOT_CONFIGURED and r.real_prob is None and not r.valid


def _manifest(tmp, entries):
    json.dump({"schema": 1, "models": entries}, open(os.path.join(tmp, "MODELS.json"), "w"))


def _entry(name="m.onnx", sha="x", scale=2.7):
    return {"file": name, "sha256": sha, "crop_scale": scale,
            "input": {"size": [80, 80]}, "output": {"classes": 3, "real_index": 1}}


def test_no_manifest_is_not_configured(tmp_path):
    p = A.MiniFASNetPAD(str(tmp_path))
    assert p.health()["state"] == A.NOT_CONFIGURED
    assert p.observe(np.zeros((90, 90, 3), np.uint8), (10, 10, 60, 60)).state == A.NOT_CONFIGURED


def test_manifest_without_files_is_not_configured(tmp_path):
    _manifest(str(tmp_path), [_entry()])
    assert A.MiniFASNetPAD(str(tmp_path)).health()["state"] == A.NOT_CONFIGURED


def test_html_file_is_error_never_a_score(tmp_path):
    (tmp_path / "m.onnx").write_text("<!DOCTYPE html><html><head></head>Page not found</html>")
    _manifest(str(tmp_path), [_entry()])
    p = A.MiniFASNetPAD(str(tmp_path))
    h = p.health()
    assert h["state"] == A.ERROR and "HTML" in h["reason"]
    r = p.observe(np.zeros((90, 90, 3), np.uint8), (10, 10, 60, 60))
    assert r.state == A.ERROR and r.real_prob is None and r.spoof_prob is None


def test_unpinned_sha_and_sha_mismatch_are_errors(tmp_path):
    (tmp_path / "m.onnx").write_bytes(b"\x08\x07binary-not-html")
    _manifest(str(tmp_path), [_entry(sha=None)])
    assert "no sha256" in A.MiniFASNetPAD(str(tmp_path)).health()["reason"]
    _manifest(str(tmp_path), [_entry(sha="0" * 64)])
    assert "mismatch" in A.MiniFASNetPAD(str(tmp_path)).health()["reason"]


class _FakeIO:
    def __init__(self, shape, name="input"):
        self.shape, self.name = shape, name


class FakeSession:                                # SIMULATED onnxruntime session
    probs = np.array([[0.02, 0.97, 0.01]], np.float32)

    def __init__(self, path, providers=None):
        pass

    def get_inputs(self):
        return [_FakeIO([1, 3, 80, 80])]

    def get_outputs(self):
        return [_FakeIO([1, 3], "probs")]

    def run(self, _names, feed):
        assert list(feed.values())[0].shape == (1, 3, 80, 80)
        return [self.probs.copy()]


@pytest.fixture
def valid_dir(tmp_path, monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    data = b"\x08\x07not-a-real-model-simulated"
    (tmp_path / "m.onnx").write_bytes(data)
    _manifest(str(tmp_path), [_entry(sha=hashlib.sha256(data).hexdigest())])
    return str(tmp_path)


def test_simulated_valid_model_gives_live(valid_dir):
    p = A.MiniFASNetPAD(valid_dir)
    assert p.health()["state"] == "READY"
    r = p.observe(np.full((200, 200, 3), 90, np.uint8), (60, 60, 140, 150))
    assert r.state == A.LIVE and abs(r.real_prob - 0.97) < 1e-6 and r.spoof_prob == pytest.approx(0.03)


def test_simulated_spoof_and_uncertain_scores(valid_dir, monkeypatch):
    p = A.MiniFASNetPAD(valid_dir)
    img, box = np.full((200, 200, 3), 90, np.uint8), (60, 60, 140, 150)
    monkeypatch.setattr(FakeSession, "probs", np.array([[0.9, 0.05, 0.05]], np.float32))
    assert p.observe(img, box).state == A.SPOOF
    monkeypatch.setattr(FakeSession, "probs", np.array([[0.4, 0.5, 0.1]], np.float32))
    assert p.observe(img, box).state == A.UNCERTAIN


def test_non_softmax_output_fails_validation(tmp_path, monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(FakeSession, "probs", np.array([[5.0, 9.0, 1.0]], np.float32))
    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    data = b"\x08\x07x"
    (tmp_path / "m.onnx").write_bytes(data)
    _manifest(str(tmp_path), [_entry(sha=hashlib.sha256(data).hexdigest())])
    h = A.MiniFASNetPAD(str(tmp_path)).health()
    assert h["state"] == A.ERROR and "non-softmax" in h["reason"]


def test_build_pad_off_mode_is_null():
    from config import DEFAULT_SETTINGS
    assert A.build_pad(DEFAULT_SETTINGS).health()["state"] == A.NOT_CONFIGURED


# ---------------------------------------------------------------- real weights (skipped when absent)
_real_manifest = os.path.join(ANTISPOOFING_MODEL_DIR, "MODELS.json")
_have_real = os.path.isfile(_real_manifest) and all(
    os.path.isfile(os.path.join(ANTISPOOFING_MODEL_DIR, m["file"])) for m in json.load(open(_real_manifest))["models"])


@pytest.mark.skipif(not _have_real, reason="real MiniFASNet ONNX weights not installed - run tools/convert_minifas.py "
                                           "(see data/models/antispoofing/MODELS.json)")
def test_real_models_load_and_run():
    p = A.MiniFASNetPAD()
    assert p.health()["state"] == "READY", p.health()
    r = p.observe(np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8), (200, 120, 360, 330))
    assert r.valid and 0.0 <= r.real_prob <= 1.0 and abs(r.real_prob + r.spoof_prob - 1.0) < 1e-6
