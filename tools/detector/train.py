"""Train the YOLO26n tomato leaf/fruit detector at 320 px on an Apple-silicon Mac.

Uses the resized copies from build_dataset.py with cache=False (no RAM cache: a 16 GB Mac runs
out of memory with cache=ram on the full set).

Usage: python tools/detector/train.py data/processed/detector/data.yaml [epochs]
"""
import sys

import torch
from ultralytics import YOLO


def main(data, epochs):
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO("yolo26n.pt")
    model.train(
        data=data,
        imgsz=320,
        epochs=epochs,
        patience=20,
        batch=32,
        device=device,
        cache=False,
        workers=4,
        seed=0,
        close_mosaic=10,
        project="runs/detector",
        name="yolo26n-320",
        exist_ok=True,
        plots=True,
    )


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 80)
