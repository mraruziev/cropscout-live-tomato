"""
Interactive viewer: the CropSCOUT A08 drives the aisle, inspects every plant with its mast cameras
and opens the side-spray valves only where disease is seen.

    python live_viewer.py                         # sim ground-truth labels decide
    python live_viewer.py --cropscout             # the team's CropSCOUT ONNX models decide (photos per plant)
    python live_viewer.py --cropscout --source sim      # the mast camera frames go to CropSCOUT
    python live_viewer.py --cropscout --source webcam   # hold a real leaf up to the webcam at each stop
    python live_viewer.py --no-camera             # no offscreen rendering at all (if your GPU driver objects)

Mouse: left-drag rotates, right-drag pans, scroll zooms.  Close the window to stop.
"""
import argparse
import time

import mujoco
import mujoco.viewer

from greenhouse_scene import Greenhouse
from mission import Mission

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--no-camera", action="store_true", help="skip the mast cameras; decisions from plant flags")
ap.add_argument("--cropscout", action="store_true", help="let the CropSCOUT models decide")
ap.add_argument("--source", default="photos", choices=["photos", "sim", "webcam"], help="what CropSCOUT looks at")
ap.add_argument("--cropscout-dir", default=None, help="path to the cropscout-live-tomato repo")
ap.add_argument("--seed", type=int, default=3, help="scene seed (which plants are sick)")
args = ap.parse_args()

gh = Greenhouse(args.seed)
cams = {}
if not args.no_camera:
    try:
        from perception import EyeCamera
        cams = {"left": EyeCamera(gh, "eye_left", 320, 240), "right": EyeCamera(gh, "eye_right", 320, 240)}
    except Exception as e:
        print(f"mast cameras unavailable ({e}); using ground-truth flags instead")

policy = None
if args.cropscout:
    from cropscout_bridge import make_policy
    policy = make_policy(gh, args.source, args.cropscout_dir, seed=args.seed)

mission = Mission(gh, cams, policy=policy)
steps = iter(mission)

with mujoco.viewer.launch_passive(gh.model, gh.data) as viewer:
    viewer.cam.lookat[:] = [2.0, 0.0, 1.2]
    viewer.cam.distance, viewer.cam.azimuth, viewer.cam.elevation = 7.0, 160, -18
    printed = 0
    while viewer.is_running():
        t0 = time.time()
        state = next(steps, None)
        if state is None:
            print(mission.summary())
            while viewer.is_running():
                viewer.sync(); time.sleep(0.05)
            break
        while printed < len(mission.log):
            o = mission.log[printed]; printed += 1
            extra = f"  {o['diagnosis']} {o['confidence']:.0%} {o['severity']}" if o.get("diagnosis") else ""
            verdict = (f"SPRAY {o['dose_ml']:.0f} mL heads {o.get('heads')}" if o["spray"] else o.get("action", "skip"))
            print(f"plant {o['plant']:2d} ({o['side']:5s} x={o['x']:.2f}): {o['label']}{extra} -> {verdict}")
        viewer.sync()
        time.sleep(max(0.0, mission.dt - (time.time() - t0)))
