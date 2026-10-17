"""Export the trained leaf/fruit detector for the browser and register it in the release metadata.

- ONNX, static 1x3x320x320 input, end-to-end output (no NMS step): 1 x 300 x 6 rows of
  x1, y1, x2, y2 (input pixels), score, class.
- Checks that onnxruntime gives the same boxes as Ultralytics on a few validation images.
- Copies the file to vision/private/cropscout-leaf-detector.onnx (gitignored) and writes its
  SHA-256 and the live settings into the leaf_detector entry of model-metadata.json.

Usage: python tools/detector/export.py runs/detector/yolo26n-320/weights/best.pt data/processed/detector
"""
import glob, hashlib, json, os, shutil, sys

import cv2
import numpy as np
import onnx
import onnxruntime as ort
from ultralytics import YOLO

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEST = os.path.join(ROOT, "vision", "private", "cropscout-leaf-detector.onnx")
METADATA = os.path.join(ROOT, "vision", "private", "model-metadata.json")
IMGSZ = 320
# Live settings read by vision/app.js (see the leaf finder notes there).
LIVE = {
    "score_threshold": 0.35,  # keep a box at or above this score
    "min_box_side": 0.15,  # ignore boxes whose longer side is under 15 % of the square
    "whole_square_side": 0.6,  # a box this big means one leaf fills the square: use the whole square
    "max_leaves": 3,  # classify at most this many boxes per frame
    "crop_padding": 1.15,  # crop a square 15 % larger than the box's longer side
}


def dims(value_info):
    return [d.dim_value for d in value_info.type.tensor_type.shape.dim]


def square_input(path):
    """Centre square, resized to 320 px, RGB CHW 0-1: what the live page feeds the detector."""
    img = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    s = min(h, w)
    img = img[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    img = cv2.resize(img, (IMGSZ, IMGSZ), interpolation=cv2.INTER_AREA)
    return img, img.transpose(2, 0, 1)[None].astype(np.float32) / 255.0


def main(weights, dataset):
    model = YOLO(weights)
    exported = model.export(format="onnx", imgsz=IMGSZ, dynamic=False, simplify=True, opset=17, batch=1, nms=False)
    graph = onnx.load(exported).graph
    in_dims, out_dims = dims(graph.input[0]), dims(graph.output[0])
    print("input", graph.input[0].name, in_dims, "output", graph.output[0].name, out_dims)
    assert in_dims == [1, 3, IMGSZ, IMGSZ], in_dims
    assert len(out_dims) == 3 and out_dims[0] == 1 and out_dims[2] == 6, out_dims

    session = ort.InferenceSession(exported, providers=["CPUExecutionProvider"])
    worst = 0.0
    for path in sorted(glob.glob(os.path.join(dataset, "images", "val", "*.jpg")))[:: 60][:8]:
        rgb, x = square_input(path)
        rows = session.run(None, {session.get_inputs()[0].name: x})[0][0]
        rows = rows[rows[:, 4] >= LIVE["score_threshold"]]
        # nms=False selects the same NMS-free one-to-one head that was exported.
        ref = model.predict(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), imgsz=IMGSZ, conf=LIVE["score_threshold"],
                            nms=False, device="cpu", verbose=False)[0]
        ref_boxes = ref.boxes.xyxy.cpu().numpy()
        assert len(rows) == len(ref_boxes), (path, len(rows), len(ref_boxes))
        if len(rows):
            order = np.lexsort((rows[:, 1], rows[:, 0]))
            ref_order = np.lexsort((ref_boxes[:, 1], ref_boxes[:, 0]))
            worst = max(worst, float(np.abs(rows[order, :4] - ref_boxes[ref_order]).max()))
    print(f"onnxruntime vs Ultralytics: max box difference {worst:.3f} px")
    assert worst < 1.0

    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    if os.path.islink(DEST):
        os.unlink(DEST)
    shutil.copyfile(exported, DEST)
    sha = hashlib.sha256(open(DEST, "rb").read()).hexdigest()
    metadata = json.load(open(METADATA, encoding="utf-8"))
    metadata["leaf_detector"] = {
        "architecture": "YOLO26n detector, end-to-end output (no NMS step)",
        "input_size": IMGSZ,
        "input": "centre square, RGB CHW, 0-1",
        "output": "1 x N x 6: x1, y1, x2, y2 (input pixels), score, class",
        "classes": list(model.names.values()),
        **LIVE,
        "onnx_sha256": sha,
    }
    with open(METADATA, "w", encoding="utf-8") as f:
        f.write(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {DEST} ({os.path.getsize(DEST) / 1e6:.1f} MB, sha256 {sha})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/processed/detector")
