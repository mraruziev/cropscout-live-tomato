#!/usr/bin/env python3
"""Turn a real video into a fake-camera clip (Y4M) for live-video.mjs.

Each frame's centre square (what the page analyses) is resized to --side px and written at
--fps, in the same limited-range BT.601 4:2:0 encoding as make_fake_camera.py. A slice of the
video can be chosen with --start/--seconds. Chrome loops the clip, so keep the run no longer
than the clip.

Usage: python -I make_video_camera.py <video> <out.y4m> [--side 480] [--fps 10] [--start 0] [--seconds 0]
"""
import argparse, os, sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_fake_camera import centre_square, resize_square, rgb_to_i420


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--side", type=int, default=480)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = to the end")
    a = ap.parse_args(argv)
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {a.video}")
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
    end = duration if a.seconds <= 0 else min(duration, a.start + a.seconds)
    n = 0
    with open(a.out, "wb") as out:
        out.write(f"YUV4MPEG2 W{a.side} H{a.side} F{a.fps}:1 Ip A1:1 C420mpeg2\n".encode())
        t = a.start
        while t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, bgr = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            sq = resize_square(centre_square(rgb), a.side)
            out.write(b"FRAME\n" + rgb_to_i420(sq, "limited", "bt601"))
            n += 1
            t = a.start + n / a.fps
    print(f"{a.out}: {n} frames, {n / a.fps:.1f} s at {a.fps} fps, {a.side}x{a.side}")


if __name__ == "__main__":
    main(sys.argv[1:])
