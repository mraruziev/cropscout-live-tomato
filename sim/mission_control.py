"""
CropSCOUT Mission Control: the robot, its camera/AI subsystem and the sprayer telemetry in ONE window.

  +--------------------------------------+---------------------------+
  |  digital twin (MuJoCo, chase camera) |  CAMERA / AI  - the frame |
  |  the A08 driving the aisle, valves   |  the model classified,    |
  |  opening on the side it treats       |  with the CropSCOUT HUD   |
  |                                      |  (live_detect.draw)       |
  |                                      +---------------------------+
  |                                      |  DECISION  verdict, dose  |
  +--------------------------------------+---------------------------+
  |  IoT TELEMETRY  tank - pump - 6 valves - used vs blanket - row map - MQTT/log           |
  +--------------------------------------------------------------------------------------+

    python mission_control.py                        # sim ground-truth labels decide
    python mission_control.py --cropscout            # CropSCOUT ONNX models decide (photo per plant)
    python mission_control.py --cropscout --source sim
    python mission_control.py --mqtt test.mosquitto.org      # also publish telemetry over MQTT
    python mission_control.py --record out/mission_control.mp4 --frames 300   # no window, write a video

Keys: q quit   space pause   s snapshot (out/snapshot_<n>.png)
Every message that drives this screen also goes to out/telemetry.jsonl (and MQTT when --mqtt is set),
so the same dashboard can sit on the real robot's feed.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import mujoco
import numpy as np

from greenhouse_scene import Greenhouse, ROW_LEN, MISSION_ROWS
from iot_bus import IoTBus
from mission import Mission
from perception import EyeCamera

W, H = 1600, 900
VIEW_W, VIEW_H = 1040, 640
BG = (22, 22, 26); PANEL = (34, 34, 40); EDGE = (60, 60, 70)
TXT = (225, 225, 230); DIM = (150, 150, 160)
GREEN = (90, 200, 120); RED = (60, 70, 235); AMBER = (40, 170, 240); BLUE = (230, 160, 70); WHITE = (245, 245, 245)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def text(img, s, xy, scale=0.55, color=TXT, thick=1):
    cv2.putText(img, s, xy, FONT, scale, color, thick, cv2.LINE_AA)


def panel(img, x0, y0, x1, y1, title=None):
    cv2.rectangle(img, (x0, y0), (x1, y1), PANEL, -1)
    cv2.rectangle(img, (x0, y0), (x1, y1), EDGE, 1)
    if title:
        text(img, title, (x0 + 12, y0 + 24), 0.6, WHITE, 2)


def bar(img, x0, y0, w, h, frac, color, label=None, value=None):
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (50, 50, 58), -1)
    cv2.rectangle(img, (x0, y0), (x0 + int(w * max(0.0, min(1.0, frac))), y0 + h), color, -1)
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), EDGE, 1)
    if label:
        text(img, label, (x0, y0 - 6), 0.5, DIM)
    if value:
        text(img, value, (x0 + w + 10, y0 + h - 4), 0.55, TXT)


def fallback_hud(frame, state):
    """Same layout as live_detect.draw() for when the CropSCOUT module is not importable."""
    h, w = frame.shape[:2]
    s = min(h, w); y0, x0 = (h - s) // 2, (w - s) // 2
    col = {"none": (80, 200, 80), "routine": (0, 190, 255), "urgent": (0, 0, 230)}.get(state.get("urgency"), (160, 160, 160))
    if state.get("status") != "identified":
        col = (160, 160, 160)
    cv2.rectangle(frame, (x0, y0), (x0 + s - 1, y0 + s - 1), col, 3)
    for sl in (np.s_[:, :x0], np.s_[:, x0 + s:], np.s_[:y0], np.s_[y0 + s:]):
        frame[sl] = (frame[sl] * 0.35).astype(np.uint8)

    def put(t, org, sc, c, th=2):
        cv2.putText(frame, t, org, FONT, sc, (0, 0, 0), th + 2, cv2.LINE_AA)
        cv2.putText(frame, t, org, FONT, sc, c, th, cv2.LINE_AA)
    put(state.get("line1", ""), (16, 34), 0.8, col)
    put(state.get("line2", ""), (16, 64), 0.6, (255, 255, 255))
    put(state.get("line3", ""), (16, 90), 0.55, (200, 200, 200))
    spray = state.get("spray", "")
    put(spray, (16, h - 52), 0.7, (0, 170, 255) if not spray.startswith("SPRAY 0%") else (200, 200, 200))
    return frame


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cropscout", action="store_true")
    ap.add_argument("--source", default="photos", choices=["photos", "sim", "webcam"])
    ap.add_argument("--cropscout-dir", default=None)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--mqtt", default=None, help="MQTT broker host (optional)")
    ap.add_argument("--record", default=None, help="write a .mp4 or .gif instead of opening a window")
    ap.add_argument("--frames", type=int, default=240, help="frames to record")
    ap.add_argument("--render-every", type=int, default=2, help="re-render the 3D view every N mission steps")
    ap.add_argument("--step-every", type=int, default=1, help="when recording: keep one frame every N mission steps")
    args = ap.parse_args()
    os.makedirs("out", exist_ok=True)

    gh = Greenhouse(args.seed)
    cams = {"left": EyeCamera(gh, "eye_left", 640, 480), "right": EyeCamera(gh, "eye_right", 640, 480)}
    policy, hud_draw = None, fallback_hud
    if args.cropscout:
        try:
            from cropscout_bridge import make_policy
            policy = make_policy(gh, args.source, args.cropscout_dir, seed=args.seed)
            try:
                import live_detect                   # the repo's own HUD (sys.path was set by the bridge)
                hud_draw = lambda f, st: (live_detect.draw(f, st, 0.0), f)[1]
            except Exception as e:
                print(f"[hud] using built-in HUD ({e})")
        except Exception as e:
            print(f"[cropscout] models not available ({e}) -> running with sim ground-truth labels instead")
            args.cropscout = False
    bus = IoTBus(broker=args.mqtt)
    mission = Mission(gh, cams, policy=policy, bus=bus)

    view = mujoco.Renderer(gh.model, VIEW_H, VIEW_W)
    cam3d = mujoco.MjvCamera(); cam3d.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam3d.distance, cam3d.azimuth, cam3d.elevation = 4.4, 22, -21

    writer, gif_frames = None, []
    if args.record:
        if args.record.lower().endswith(".gif"):
            pass
        else:
            writer = cv2.VideoWriter(args.record, cv2.VideoWriter_fourcc(*"mp4v"), 12, (W, H))
    else:
        cv2.namedWindow("CropSCOUT Mission Control", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("CropSCOUT Mission Control", W, H)

    view_img = None
    cam_panel = np.zeros((420, 560, 3), np.uint8)
    thumb = None
    last_plant_shown = None
    n_frames, snap = 0, 0
    t_wall = time.time()
    paused = False
    plants = gh.mission_plants
    xs = [p[1] for p in plants]
    xmin, xmax = min(xs) - 0.5, max(xs) + 0.5

    for k, state in enumerate(mission):
        if args.record and k % args.step_every:
            continue
        if k % args.render_every == 0 or view_img is None or state["mode"] != "drive":
            cam3d.lookat[:] = [mission.x + 0.9, 0.0, 1.0]
            view.update_scene(gh.data, camera=cam3d)
            view_img = cv2.cvtColor(view.render(), cv2.COLOR_RGB2BGR)
        li = mission.last_inspection
        if li is not None and li["plant"][0] != last_plant_shown:
            last_plant_shown = li["plant"][0]
            frame = li["frame"]
            if frame is None:
                frame = np.ascontiguousarray(cams[li["side"]].rgb()[..., ::-1])
            fh, fw = frame.shape[:2]
            if fw < 600:                                             # a 256x256 leaf photo: letterbox to 800x600
                canvas = np.full((600, 800, 3), 28, np.uint8)
                sq = cv2.resize(frame, (600, 600), interpolation=cv2.INTER_CUBIC)
                canvas[:, 100:700] = sq
                frame = canvas
            else:
                frame = cv2.resize(frame, (800, 600), interpolation=cv2.INTER_CUBIC)
            if li["hud"]:
                frame = hud_draw(frame, li["hud"])
            cam_panel = cv2.resize(frame, (560, 420))
            if args.cropscout and args.source == "photos":
                thumb = cv2.resize(np.ascontiguousarray(cams[li["side"]].rgb()[..., ::-1]), (180, 135))
            else:
                thumb = None

        # ---------------------------------------------------------------- compose
        ui = np.full((H, W, 3), BG[0], np.uint8); ui[:] = BG
        ui[0:VIEW_H, 0:VIEW_W] = view_img
        text(ui, "DIGITAL TWIN  -  CropSCOUT A08 in MuJoCo (your CAD)", (12, 24), 0.6, WHITE, 2)
        mode = state["mode"]
        mode_txt = {"drive": "driving", "look": "inspecting", "spray": "SPRAYING"}[mode]
        mode_col = {"drive": DIM, "look": AMBER, "spray": BLUE}[mode]
        text(ui, f"{mode_txt}   x = {mission.x:.2f} m   t = {mission.t:5.1f} s", (12, VIEW_H - 14), 0.6, mode_col, 2)

        # camera / AI panel
        panel(ui, VIEW_W, 0, W, 450, "CAMERA / AI SUBSYSTEM  (CropSCOUT pipeline)")
        ui[30:450, VIEW_W:W] = cam_panel
        if thumb is not None:
            ui[30:165, W - 180:W] = thumb
            cv2.rectangle(ui, (W - 180, 30), (W - 1, 164), EDGE, 1)
            text(ui, "mast camera (sim)", (W - 176, 160), 0.42, WHITE, 1)
        src_txt = {"photos": "input: real leaf photo (PlantVillage)", "sim": "input: mast camera frame",
                   "webcam": "input: webcam"}[args.source] if args.cropscout else "input: mast camera frame (sim labels)"
        text(ui, src_txt, (VIEW_W + 12, 444), 0.45, DIM)

        # decision card
        panel(ui, VIEW_W, 450, W, VIEW_H, "DECISION")
        if li is not None:
            o = li["obs"]
            side = o["side"]
            text(ui, f"plant {o['plant']}  {side} row  x={o['x']:.2f} m", (VIEW_W + 12, 452 + 46), 0.5, DIM)
            diag = o.get("diagnosis") or o.get("label", "?")
            conf = o.get("confidence")
            text(ui, f"{diag}" + (f"  {conf * 100:.0f}%" if isinstance(conf, (int, float)) else ""),
                 (VIEW_W + 12, 452 + 74), 0.62, RED if o.get("spray") else GREEN, 2)
            if o.get("spray"):
                text(ui, f"SPRAY {o['dose_ml']:.0f} mL  heads {o.get('heads')}  ~{o.get('spray_seconds', o['dose_ml'] / 10):.1f} s pump",
                     (VIEW_W + 12, 452 + 104), 0.55, BLUE, 2)
                if o.get("product"):
                    text(ui, f"{o['product']}  severity {o.get('severity')}", (VIEW_W + 12, 452 + 130), 0.48, DIM)
            else:
                text(ui, o.get("reason") or "no spray", (VIEW_W + 12, 452 + 104), 0.5, GREEN)
            text(ui, f"source: {o.get('image', '')[-52:]}", (VIEW_W + 12, 452 + 158), 0.4, DIM)
            text(ui, f"line of sight {'clear' if o.get('clear_line_of_sight') else 'partly occluded'}", (VIEW_W + 12, 452 + 180), 0.45, DIM)

        # telemetry strip
        panel(ui, 0, VIEW_H, W, H, "IoT TELEMETRY  -  cropscout/a08/#  (out/telemetry.jsonl" + (f", mqtt://{args.mqtt}" if bus.mqtt else "") + ")")
        y = VIEW_H + 60
        # tank
        bar(ui, 20, y + 10, 220, 22, mission.tank_ml / mission.tank_full, BLUE, "tank (5 gal)",
            f"{mission.tank_ml / 1000:.2f} L  {100 * mission.tank_ml / mission.tank_full:.1f}%")
        # pump + valves
        text(ui, "pump", (20, y + 72), 0.5, DIM)
        cv2.circle(ui, (80, y + 66), 9, BLUE if mission.pump_on else (60, 60, 70), -1)
        text(ui, "valves", (120, y + 72), 0.5, DIM)
        for i, name in enumerate(["L24", "L42", "L60", "R24", "R42", "R60"]):
            cx = 190 + i * 58
            cv2.circle(ui, (cx, y + 66), 9, BLUE if mission.valves[i] else (60, 60, 70), -1)
            text(ui, name, (cx - 14, y + 92), 0.42, DIM)
        # usage
        s = mission.summary()
        bar(ui, 20, y + 130, 220, 18, s["targeted_ml"] / max(1.0, s["blanket_ml"]), GREEN, "spray used vs blanket",
            f"{s['targeted_ml']:.0f} mL of {s['blanket_ml']:.0f} mL   saved {s['saving_pct']:.0f}%")
        text(ui, f"inspected {s['inspected']}/{s['plants']}   sprayed {s['sprayed']}", (20, y + 185), 0.52, TXT)
        # row map
        mx0, mx1, my = 640, 1180, y + 20
        text(ui, "row map  (left row / right row, robot = white box)", (mx0, my - 2), 0.45, DIM)
        for row_y, line_y in ((MISSION_ROWS[1], my + 30), (MISSION_ROWS[0], my + 110)):
            cv2.line(ui, (mx0, line_y), (mx1, line_y), (70, 70, 80), 2)
            for p in plants:
                if abs(p[2] - row_y) > 1e-6:
                    continue
                px = int(mx0 + (p[1] - xmin) / (xmax - xmin) * (mx1 - mx0))
                st = mission.status.get(p[0], "pending")
                col = {"pending": (90, 90, 100), "inspecting": WHITE, "healthy": GREEN, "spray": RED, "flag": AMBER}[st]
                cv2.circle(ui, (px, line_y), 8 if st != "pending" else 6, col, -1)
        rx = int(mx0 + (mission.x + 0.18 - xmin) / (xmax - xmin) * (mx1 - mx0))
        cv2.rectangle(ui, (rx - 10, my + 60), (rx + 10, my + 80), WHITE, -1)
        text(ui, f"aisle position {mission.x:.2f} m", (mx0, my + 150), 0.45, DIM)
        # legend + status
        lx = 1230
        for i, (lab, col) in enumerate([("healthy", GREEN), ("sprayed", RED), ("flag / remove", AMBER), ("pending", (90, 90, 100))]):
            cv2.circle(ui, (lx + 8, my + 10 + i * 26), 7, col, -1)
            text(ui, lab, (lx + 24, my + 15 + i * 26), 0.45, TXT)
        text(ui, f"policy: {'CropSCOUT ONNX models' if args.cropscout else 'sim ground-truth labels'}", (lx, my + 130), 0.45, DIM)
        text(ui, f"messages: {len(bus.history)}", (lx, my + 152), 0.45, DIM)

        # ---------------------------------------------------------------- output
        n_frames += 1
        if args.record:
            if writer is not None:
                writer.write(ui)
            else:
                from PIL import Image
                gif_frames.append(Image.fromarray(cv2.cvtColor(cv2.resize(ui, (800, 450)), cv2.COLOR_BGR2RGB)))
            if n_frames >= args.frames:
                break
        else:
            cv2.imshow("CropSCOUT Mission Control", ui)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
                while paused:
                    key = cv2.waitKey(50) & 0xFF
                    if key == ord(" "):
                        paused = False
                    if key in (ord("q"), 27):
                        paused = False; break
            if key == ord("s"):
                snap += 1
                cv2.imwrite(f"out/snapshot_{snap}.png", ui)
            # real-time pacing
            dt_wall = time.time() - t_wall
            if dt_wall < mission.dt:
                time.sleep(mission.dt - dt_wall)
            t_wall = time.time()

    print(mission.summary())
    bus.close()
    if args.record:
        if writer is not None:
            writer.release()
        else:
            gif_frames[0].save(args.record, save_all=True, append_images=gif_frames[1:], duration=90, loop=0, optimize=True)
        print("wrote", args.record, f"({n_frames} frames)")
    else:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
