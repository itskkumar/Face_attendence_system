"""
Throw-away converter: official MiniFASNet .pth -> ONNX (+ softmax) and MODELS.json sha256 update.

Run in a SEPARATE venv that has torch (the runtime environment stays torch-free):

    python -m venv /tmp/conv && . /tmp/conv/bin/activate && pip install torch onnx onnxruntime numpy
    git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing /tmp/sfas
    python tools/convert_minifas.py --repo /tmp/sfas --out data/models/antispoofing

Before trusting the output, compare src/anti_spoof_predict.py, src/generate_patches.py and
src/utility.py in the cloned repo against antispoof.preprocess (crop scale, BGR, 0..255, 3-class
softmax, class 1 = real) and check the repo LICENSE against MODELS.json.
"""
import argparse
import hashlib
import json
import os
import sys
from collections import OrderedDict


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path to a clone of Silent-Face-Anti-Spoofing")
    ap.add_argument("--out", default=os.path.join("data", "models", "antispoofing"))
    args = ap.parse_args()

    import numpy as np
    import onnxruntime as ort
    import torch

    sys.path.insert(0, args.repo)
    import src.model_lib.MiniFASNet as _M                        # noqa: E402
    MODEL_MAPPING = {n: getattr(_M, n) for n in ('MiniFASNetV1', 'MiniFASNetV2', 'MiniFASNetV1SE', 'MiniFASNetV2SE')}
    from src.utility import get_kernel, parse_model_name         # noqa: E402

    manifest_path = os.path.join(args.out, "MODELS.json")
    manifest = json.load(open(manifest_path))
    weights_dir = os.path.join(args.repo, "resources", "anti_spoof_models")

    for entry in manifest["models"]:
        pth = os.path.join(weights_dir, entry["file"].replace(".onnx", ".pth"))
        if not os.path.isfile(pth):
            raise SystemExit(f"missing weights: {pth}")
        h_in, w_in, model_type, scale = parse_model_name(os.path.basename(pth))
        assert abs((scale or 1.0) - entry["crop_scale"]) < 1e-6, f"scale mismatch for {pth}"
        assert (h_in, w_in) == tuple(entry["input"]["size"])
        net = MODEL_MAPPING[model_type](conv6_kernel=get_kernel(h_in, w_in), num_classes=3)
        state = torch.load(pth, map_location="cpu")
        state = OrderedDict((k[7:] if k.startswith("module.") else k, v) for k, v in state.items())
        net.load_state_dict(state)
        net.eval()

        class WithSoftmax(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.m = m

            def forward(self, x):
                return torch.softmax(self.m(x), dim=1)

        wrapped = WithSoftmax(net).eval()
        out_path = os.path.join(args.out, entry["file"])
        dummy = torch.randn(1, 3, h_in, w_in) * 40 + 120          # 0..255-ish range, like real input
        torch.onnx.export(wrapped, dummy, out_path, input_names=["input"], output_names=["probs"],
                          opset_version=12, dynamo=False)
        sess = ort.InferenceSession(out_path, providers=["CPUExecutionProvider"])
        ref = wrapped(dummy).detach().numpy()
        got = sess.run(None, {"input": dummy.numpy()})[0]
        assert np.allclose(ref, got, atol=1e-4), f"ONNX/torch mismatch for {entry['file']}"
        entry["sha256"] = sha256(out_path)
        print(f"{entry['file']}: ok, sha256 {entry['sha256']}")

    lic = os.path.join(args.repo, "LICENSE")
    if os.path.isfile(lic):
        print("repo LICENSE first line:", open(lic).readline().strip(), "-> confirm and update MODELS.json 'license'")
    json.dump(manifest, open(manifest_path, "w"), indent=2)
    print("updated", manifest_path)


if __name__ == "__main__":
    main()
