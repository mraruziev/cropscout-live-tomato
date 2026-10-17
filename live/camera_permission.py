"""Ask macOS for camera permission and wait for the answer.

Run this once from the terminal you will use for the demo:
    .venv/bin/python live/camera_permission.py
"""
import sys
import threading

import AVFoundation as AV

NAMES = {0: "not determined", 1: "restricted", 2: "denied", 3: "authorized"}
status = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
print(f"camera permission for this terminal: {NAMES.get(status, status)}")
if status == 3:
    sys.exit(0)
if status in (1, 2):
    print("Denied. Open System Settings > Privacy & Security > Camera, enable this terminal app, then rerun.")
    sys.exit(1)

done = threading.Event()
result = {}

def cb(granted):
    result["granted"] = bool(granted)
    done.set()

print("Requesting... click Allow in the macOS dialog (waiting up to 120 s)")
AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeVideo, cb)
# the completion handler needs a running main loop on macOS
from Foundation import NSRunLoop, NSDate
deadline = NSDate.dateWithTimeIntervalSinceNow_(120)
while not done.is_set() and NSDate.date().compare_(deadline) < 0:
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
print("granted" if result.get("granted") else "not granted (timed out or declined)")
sys.exit(0 if result.get("granted") else 1)
