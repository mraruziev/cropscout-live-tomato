"""Export a fine-tuned classifier to ONNX the way the page expects it.

Static 1x3x224x224 input named "images", softmax output "output0", opset 18, batch 1 (the page
runs one leaf at a time). The class order is checked against the metadata, onnxruntime is
checked against PyTorch on a few real images, and the training path is removed from the
model's description field.

With --install the ONNX replaces the model in vision/private/ (a link there is replaced by the
file, never written through) and its SHA-256 and the checkpoint's go into model-metadata.json.
"tomato-leaf" installs a condition model as the tomato-leaf specialist (its own entry in
condition_specialists), so the general condition model, used for every other crop, is unchanged.

Usage: python -I tools/classifier/export.py <best.pt> <out.onnx> condition|tomato-leaf|crop-view [--install] [images...]
"""
import hashlib, json, os, shutil, sys

import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image
from ultralytics import YOLO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import PRIVATE, load_metadata, photo_tensor

DEST = {"condition": ("disease", "cropscout-disease.onnx"), "crop-view": ("crop_view", "cropscout-crop-view.onnx"),
        "tomato-leaf": (None, "cropscout-tomato-leaf.onnx")}


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def install(weights, onnx_path, kind):
    key, name = DEST[kind]
    dest = os.path.join(PRIVATE, name)
    if os.path.islink(dest):
        os.unlink(dest)
    shutil.copyfile(onnx_path, dest)
    meta_path = os.path.join(PRIVATE, "model-metadata.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    if kind == "tomato-leaf":
        # Same 46-class output as the general model; the page compares only its tomato-leaf classes.
        entry = {"id": "tomato-leaf", "families": ["Tomato_leaf"], "classes": meta["disease"]["classes"],
                 "checkpoint_sha256": sha256(weights), "onnx_sha256": sha256(dest)}
        specs = [s for s in meta.get("condition_specialists", []) if s["id"] != "tomato-leaf"]
        meta["condition_specialists"] = specs + [entry]
        target = entry
    else:
        meta[key]["checkpoint_sha256"] = sha256(weights)
        meta[key]["onnx_sha256"] = sha256(dest)
        target = meta[key]
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"installed {dest}; metadata onnx_sha256 = {target['onnx_sha256']}")


def main(weights, out, kind, images, do_install=False):
    meta = load_metadata()
    want = meta["crop_view"]["classes"] if kind == "crop-view" else [c["label"] for c in meta["disease"]["classes"]]
    model = YOLO(weights)
    names = [model.names[i] for i in range(len(model.names))]
    if names != want:
        raise SystemExit(f"class order differs from the metadata: {names[:5]}... vs {want[:5]}...")
    path = model.export(format="onnx", imgsz=224, batch=1, opset=18, simplify=True, dynamic=False, device="cpu")
    m = onnx.load(path)
    for p in m.metadata_props:
        if p.key == "description":
            p.value = "Ultralytics YOLO26n-cls model (CropSCOUT Live)"
    onnx.save(m, path)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if os.path.abspath(path) != os.path.abspath(out):
        shutil.copyfile(path, out)

    sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
    assert sess.get_inputs()[0].name == "images" and list(sess.get_inputs()[0].shape) == [1, 3, 224, 224]
    assert sess.get_outputs()[0].name == "output0" and list(sess.get_outputs()[0].shape) == [1, len(want)]
    net = model.model.float().eval().cpu()
    worst = 0.0
    for img in images:
        x = photo_tensor(Image.open(img).convert("RGB"))
        a = sess.run(None, {"images": x})[0][0]
        with torch.no_grad():
            b = net(torch.from_numpy(x))
            b = (b[0] if isinstance(b, (list, tuple)) else b)[0].numpy()
        worst = max(worst, float(np.abs(a - b).max()))
        assert abs(a.sum() - 1) < 1e-3, "output is not a softmax"
    print(f"wrote {out} ({os.path.getsize(out)/1e6:.1f} MB), sha256 {hashlib.sha256(open(out, 'rb').read()).hexdigest()}")
    print(f"max |onnxruntime - pytorch| over {len(images)} images: {worst:.2e}")
    if do_install:
        install(weights, out, kind)


if __name__ == "__main__":
    rest = sys.argv[4:]
    main(sys.argv[1], sys.argv[2], sys.argv[3], [a for a in rest if a != "--install"], "--install" in rest)
