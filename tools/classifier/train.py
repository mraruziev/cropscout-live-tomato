"""Fine-tune a YOLO26n classifier at 224 px on an Apple-silicon Mac.

Starts from the model's current checkpoint, so the class list and the ONNX contract stay the same,
and trains on a folder from assemble.py (symlinks to resized copies) with cache=False: a RAM
cache of the full set does not fit a 16 GB Mac. Every epoch is saved, because the checkpoint is
chosen on real photos (tools/classifier/evaluate.py), not on validation accuracy.

Usage: python tools/classifier/train.py <checkpoint.pt> <dataset dir> <run name> [epochs] [lr0]
"""
import sys

import torch
from ultralytics import YOLO


def main(checkpoint, data, name, epochs, lr0):
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(checkpoint)
    model.train(
        data=data,
        imgsz=224,
        epochs=epochs,
        patience=epochs,
        batch=64,
        device=device,
        cache=False,
        workers=4,
        seed=26,
        deterministic=True,
        optimizer="AdamW",
        lr0=lr0,
        lrf=0.1,
        cos_lr=True,
        warmup_epochs=0.5,
        hsv_s=0.35,
        hsv_v=0.25,
        degrees=12.0,
        translate=0.08,
        scale=0.25,
        flipud=0.08,
        fliplr=0.5,
        auto_augment="randaugment",
        erasing=0.25,
        save_period=1,
        project="runs/classifier",
        name=name,
        exist_ok=True,
        plots=True,
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3],
         int(sys.argv[4]) if len(sys.argv) > 4 else 10, float(sys.argv[5]) if len(sys.argv) > 5 else 2e-4)
