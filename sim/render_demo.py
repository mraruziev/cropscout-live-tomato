"""
Headless demo: runs the mission, writes into the output folder
  greenhouse_demo.xml   the scene (open with: python -m mujoco.viewer --mjcf out/greenhouse_demo.xml)
  greenhouse_hero.png   overview + top view + mast camera + ground-truth labels
  greenhouse_sweep.gif  the robot driving the aisle and spraying
  mission_log.json      per-plant observations + pesticide summary

    python render_demo.py                     (writes to ./out)
    python render_demo.py out --cropscout     (CropSCOUT models decide, photos per plant)
    python render_demo.py out --cropscout --source sim   (the mast camera frames go to the models)

Works on a laptop with no GPU. On Linux servers without a display: MUJOCO_GL=egl or osmesa.
"""
import argparse
import json
import os

import mujoco
import numpy as np
from PIL import Image, ImageDraw

from greenhouse_scene import Greenhouse
from mission import Mission
from perception import EyeCamera, detect_ground_truth

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("out", nargs="?", default="out")
ap.add_argument("--cropscout", action="store_true", help="let the CropSCOUT models decide")
ap.add_argument("--source", default="photos", choices=["photos", "sim", "webcam"])
ap.add_argument("--cropscout-dir", default=None)
ap.add_argument("--seed", type=int, default=3)
ap.add_argument("--gif-frames", type=int, default=60)
args = ap.parse_args()
OUT = args.out
os.makedirs(OUT, exist_ok=True)

gh = Greenhouse(args.seed)
gh.save_xml(os.path.join(OUT, "greenhouse_demo.xml"))
cams = {"left": EyeCamera(gh, "eye_left", 480, 360), "right": EyeCamera(gh, "eye_right", 480, 360)}
big = mujoco.Renderer(gh.model, 720, 1280)


def render(cam):
    big.update_scene(gh.data, camera=cam)
    return big.render().copy()


def label_image(cam):
    """Colour the segmentation render by class: the free ground-truth labels."""
    seg = cam.segmentation()
    img = np.zeros((*seg.shape, 3), dtype=np.uint8)
    for gid in np.unique(seg):
        if gid < 0:
            continue
        name, pid, mask = gh.geom_names[int(gid)], gh.geom_plant(int(gid)), seg == gid
        if pid is not None and "_fruit" in name:
            img[mask] = (230, 40, 30) if gh.model.geom_rgba[int(gid)][0] > 0.6 else (120, 200, 60)
        elif pid is not None and "_leafd" in name:
            img[mask] = (215, 160, 30)
        elif pid is not None and "_leaf" in name:
            img[mask] = (40, 160, 50)
        elif pid is not None:
            img[mask] = (90, 110, 60)
        else:
            img[mask] = (70, 70, 80)
    return img


# ------------------------------------------------------------------ perception self-check
plant = next(p for p in gh.mission_plants if p[3])
side = "left" if plant[2] > 0 else "right"
gh.set_pose(plant[1] - 0.18)
dets = detect_ground_truth(cams[side])
true_pos = [gh.data.geom_xpos[gid] for gid in gh.plant_geoms(plant[0], "fruit")]
errs = [min(np.linalg.norm(d.xyz - p) for p in true_pos)
        for d in dets if d.plant_id == plant[0] and d.label.startswith("fruit") and d.xyz is not None]
own = [d for d in dets if d.plant_id == plant[0]]
print(f"perception check on plant {plant[0]} ({side}, {plant[4]}): {len(dets)} detections, {len(own)} on this plant "
      f"({sum(d.label == 'leaf_blight' for d in own)} blight leaves)"
      + (f", fruit 3D error mean {100*np.mean(errs):.1f} cm" if errs else ""))

# ------------------------------------------------------------------ run the mission, grab frames
policy = None
if args.cropscout:
    from cropscout_bridge import make_policy
    policy = make_policy(gh, args.source, args.cropscout_dir, seed=args.seed)
mission = Mission(gh, cams, policy=policy)
n_states_est = int((8.0 + 1.8) / 0.35 / 0.05) + 60 * 8 + 32 * 8
every = max(1, n_states_est // args.gif_frames)
frames, hero = [], None
for k, state in enumerate(mission):
    if state["mode"] == "spray" and hero is None:
        s = "left" if gh.mission_plants[[p[0] for p in gh.mission_plants].index(state["plant"])][2] > 0 else "right"
        hero = (render("overview"), render("top"), cams[s].rgb(), label_image(cams[s]), state)
    if k % every == 0:
        frames.append(Image.fromarray(render("aisle")).resize((640, 360)))
summary = mission.summary()
print(summary)
for o in mission.log:
    print(f"  plant {o['plant']:2d} {o['side']:5s} x={o['x']:.2f}  {o['label']:28s} "
          f"{'SPRAY ' + str(round(o['dose_ml'],1)) + ' mL heads ' + str(o.get('heads')) if o['spray'] else o.get('action', 'skip')}")

# ------------------------------------------------------------------ hero image
if hero is None:
    gh.set_pose(plant[1] - 0.18)
    hero = (render("overview"), render("top"), cams[side].rgb(), label_image(cams[side]), None)
ov, top, eye, lab, st = hero
canvas = Image.new("RGB", (1280, 720 + 360), (20, 20, 24))
canvas.paste(Image.fromarray(ov), (0, 0))
canvas.paste(Image.fromarray(top).resize((480, 270)), (0, 720))
canvas.paste(Image.fromarray(eye).resize((480, 360)), (480, 720))
canvas.paste(Image.fromarray(lab).resize((320, 240)), (960, 720))
dr = ImageDraw.Draw(canvas)
who = "CropSCOUT models decide" if args.cropscout else "sim ground-truth labels decide"
lines = ["CropSCOUT A08 in a MuJoCo tomato greenhouse", f"policy: {who}",
         f"plants inspected: {summary['plants']}   sprayed: {summary['sprayed']}",
         f"spray used: {summary['targeted_ml']:.0f} mL vs {summary['blanket_ml']:.0f} mL blanket  (-{summary['saving_pct']:.0f}%)",
         "left: top view   middle: mast camera   right: ground-truth labels"]
for i, t in enumerate(lines):
    dr.text((8, 996 + 16 * i), t, fill=(230, 230, 230))
canvas.save(os.path.join(OUT, "greenhouse_hero.png"))

frames[0].save(os.path.join(OUT, "greenhouse_sweep.gif"), save_all=True, append_images=frames[1:],
               duration=120, loop=0, optimize=True)
with open(os.path.join(OUT, "mission_log.json"), "w") as f:
    json.dump(dict(summary=summary, plants=mission.log), f, indent=2, default=str)
print(f"wrote {OUT}/greenhouse_hero.png, greenhouse_sweep.gif ({len(frames)} frames), mission_log.json")
