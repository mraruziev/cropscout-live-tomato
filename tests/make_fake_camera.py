#!/usr/bin/env python3
"""Build a fake-camera Y4M clip for Chrome's --use-file-for-fake-video-capture.

The source image is centre-cropped to a square, the square is resized to the
frame's shorter side and pasted in the middle of a mid-grey frame. The frame is
written as an uncompressed YUV4MPEG2 (4:2:0) clip that repeats the same frame.
Chrome loops the clip, so a short clip behaves like a perfectly still camera.

The exact square that was pasted into the frame is also written next to the
clip as <out-without-.y4m>.square.png, so the upload path can analyse the same
pixels the live path sees.

Usage:
    make_fake_camera.py <image | synthetic:grey | synthetic:noise | synthetic:patches> <out.y4m>
        [--width 1920] [--height 1080] [--frames 30]
        [--range limited|full] [--matrix bt601|bt709] [--seed 7]

Colour encoding: Chrome's Y4M reader accepts the C420* tags but ignores them
and treats every frame as 4:2:0 YUV in a fixed colour space. --range and
--matrix choose how RGB is encoded so that what Chrome decodes matches the
source pixels; the defaults were picked with `live-e2e.mjs --calibrate`.

Needs numpy and opencv-python. No ffmpeg required.
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

GREY = 128

# Luma coefficients (Kr, Kb) per matrix.
MATRICES = {
    "bt601": (0.299, 0.114),
    "bt709": (0.2126, 0.0722),
}


def calibration_patches() -> np.ndarray:
    """6x6 RGB patch grid: greys, primaries, secondaries and leaf/fruit tones."""
    colours = [
        (0, 0, 0), (32, 32, 32), (64, 64, 64), (128, 128, 128), (192, 192, 192), (255, 255, 255),
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
        (128, 0, 0), (0, 128, 0), (0, 0, 128), (128, 128, 0), (0, 128, 128), (128, 0, 128),
        (34, 139, 34), (85, 107, 47), (107, 142, 35), (154, 205, 50), (60, 90, 30), (120, 160, 70),
        (200, 30, 30), (230, 90, 40), (240, 200, 60), (139, 69, 19), (160, 120, 60), (210, 180, 140),
        (90, 60, 40), (180, 40, 60), (100, 150, 200), (220, 220, 180), (50, 70, 50), (170, 190, 120),
    ]
    return np.array(colours, dtype=np.uint8).reshape(6, 6, 3)


def load_source(spec: str, side: int, seed: int) -> np.ndarray:
    """Return an RGB uint8 image (any size) for an image path or synthetic spec."""
    if spec.startswith("synthetic:"):
        kind = spec.split(":", 1)[1]
        if kind == "grey":
            return np.full((side, side, 3), GREY, dtype=np.uint8)
        if kind == "noise":
            # Coarse colour noise: fine per-pixel noise would average out to grey
            # once the app downsamples the square to 224 px.
            rng = np.random.default_rng(seed)
            cells = rng.integers(0, 256, size=(48, 48, 3), dtype=np.uint8)
            return cv2.resize(cells, (side, side), interpolation=cv2.INTER_NEAREST)
        if kind == "patches":
            # 6x6 grid of flat colour patches, used by `live-e2e.mjs --calibrate`.
            return cv2.resize(calibration_patches(), (side, side), interpolation=cv2.INTER_NEAREST)
        raise SystemExit(f"unknown synthetic source: {spec}")

    raw = cv2.imread(spec, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise SystemExit(f"could not read image: {spec}")
    if raw.dtype != np.uint8:
        raw = cv2.convertScaleAbs(raw, alpha=255.0 / max(1, int(raw.max())))
    if raw.ndim == 3 and raw.shape[2] == 4:
        # Composite transparency onto the same grey as the frame background.
        bgr = raw[:, :, :3].astype(np.float32)
        alpha = raw[:, :, 3:4].astype(np.float32) / 255.0
        bgr = bgr * alpha + GREY * (1.0 - alpha)
        bgr = np.clip(np.rint(bgr), 0, 255).astype(np.uint8)
    else:
        # IMREAD_COLOR applies EXIF orientation, matching the browser's
        # imageOrientation: 'from-image'.
        bgr = cv2.imread(spec, cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def centre_square(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    side = min(h, w)
    y0 = (h - side) // 2
    x0 = (w - side) // 2
    return rgb[y0:y0 + side, x0:x0 + side]


def resize_square(square: np.ndarray, side: int) -> np.ndarray:
    if square.shape[0] == side:
        return square.copy()
    interp = cv2.INTER_AREA if square.shape[0] > side else cv2.INTER_CUBIC
    return cv2.resize(square, (side, side), interpolation=interp)


def rgb_to_i420(rgb: np.ndarray, value_range: str, matrix: str) -> bytes:
    """Encode an RGB frame (even width/height) as planar I420 bytes."""
    kr, kb = MATRICES[matrix]
    kg = 1.0 - kr - kb
    f = rgb.astype(np.float32)
    r, g, b = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    y = kr * r + kg * g + kb * b
    cb = (b - y) / (2.0 * (1.0 - kb))
    cr = (r - y) / (2.0 * (1.0 - kr))
    if value_range == "full":
        y_out = y
        cb_out = cb + 128.0
        cr_out = cr + 128.0
    else:  # limited / studio swing
        y_out = 16.0 + y * (219.0 / 255.0)
        cb_out = 128.0 + cb * (224.0 / 255.0)
        cr_out = 128.0 + cr * (224.0 / 255.0)
    h, w = y_out.shape
    # 4:2:0 chroma: average each 2x2 block.
    cb_sub = cb_out.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    cr_sub = cr_out.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
    planes = [
        np.clip(np.rint(p), 0, 255).astype(np.uint8)
        for p in (y_out, cb_sub, cr_sub)
    ]
    return b"".join(p.tobytes() for p in planes)


def square_png_path(out_path: str) -> str:
    base = out_path[:-4] if out_path.lower().endswith(".y4m") else out_path
    return base + ".square.png"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", help="source image path, or synthetic:grey / synthetic:noise")
    parser.add_argument("out", help="output .y4m path")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--range", dest="value_range", choices=("limited", "full"), default="limited")
    parser.add_argument("--matrix", choices=tuple(MATRICES), default="bt601")
    parser.add_argument("--seed", type=int, default=7, help="seed for synthetic:noise")
    args = parser.parse_args(argv)

    if args.width % 2 or args.height % 2:
        raise SystemExit("--width and --height must be even (4:2:0 chroma)")
    if args.frames < 1:
        raise SystemExit("--frames must be >= 1")

    side = min(args.width, args.height)
    source = load_source(args.image, side, args.seed)
    square = resize_square(centre_square(source), side)

    frame = np.full((args.height, args.width, 3), GREY, dtype=np.uint8)
    y0 = (args.height - side) // 2
    x0 = (args.width - side) // 2
    frame[y0:y0 + side, x0:x0 + side] = square

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)

    png_path = square_png_path(args.out)
    if not cv2.imwrite(png_path, cv2.cvtColor(square, cv2.COLOR_RGB2BGR)):
        raise SystemExit(f"could not write {png_path}")

    colour_tag = "C420jpeg" if args.value_range == "full" else "C420mpeg2"
    header = f"YUV4MPEG2 W{args.width} H{args.height} F{args.fps}:1 Ip A1:1 {colour_tag}\n".encode("ascii")
    payload = rgb_to_i420(frame, args.value_range, args.matrix)
    tmp_path = args.out + ".tmp"
    with open(tmp_path, "wb") as handle:
        handle.write(header)
        for _ in range(args.frames):
            handle.write(b"FRAME\n")
            handle.write(payload)
    os.replace(tmp_path, args.out)

    print(
        f"wrote {args.out} ({args.width}x{args.height}, {args.frames} frames, "
        f"{args.value_range}/{args.matrix}) and {png_path} ({side}x{side})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
