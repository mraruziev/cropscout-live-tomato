# CropSCOUT A08 — digital twin, camera/AI subsystem and sprayer IoT in one loop

**What each piece is (one line each)**

- **A08 robot** — a tracked greenhouse rover with a 5-gal tank and two 1.27 m masts carrying six side-facing
  nozzles (24 / 42 / 60 in), each on its own solenoid, so it treats one plant, one side, one height band at a time.
- **CropSCOUT vision** ([repo](https://github.com/mraruziev/cropscout-live-tomato)) — a two-stage on-device
  classifier (crop-view gate → 26-class condition model, ONNX on the Jetson and in the browser) that abstains unless
  a tomato leaf *and* its condition pass every safeguard.
- **Spray rules** — a per-condition dose table in mL per plant, scaled by the lesion area measured in the same
  frame; viruses get "remove", healthy leaves and non-infectious disorders get zero.
- **Digital twin** — your actual A08 CAD inside a MuJoCo high-wire tomato greenhouse whose diseased plants carry
  real PlantVillage leaflets, so mast cameras, valves and tank behave like the hardware before the hardware exists.
- **Mission Control** — one screen: the twin, the exact frame the model is judging with the live HUD, the decision,
  and the sprayer telemetry (tank, pump, six valves, used vs blanket, row map).
- **IoT bus** — every inspection, valve event and tank reading is a JSON message on `cropscout/a08/#`, logged
  locally and optionally published over MQTT; the dashboard cannot tell whether the sender is the twin or the robot.
- **Result** — on a 30-plant aisle with 6 infected plants the targeted pass used 130 mL instead of 900 mL (−86 %).

**Where it lives.** This folder is `sim/` in the CropSCOUT repo, so `--cropscout` finds the repo (`live/`,
`vision/spray-rules.json`, `live/models/`) one level up with no `--cropscout-dir`. The `.bat` files are for Windows;
on a Mac or Linux:

```bash
python3.11 -m venv sim/.venv && sim/.venv/bin/pip install -r sim/requirements.txt -r sim/requirements-cropscout.txt
cd sim && .venv/bin/python mission_control.py --cropscout      # or: render_demo.py out --cropscout (headless)
```

## Mission Control (the integrated demo)

`7_MISSION_CONTROL.bat` (or F5 → *Mission Control*) opens one window:

| area | what it shows |
| --- | --- |
| left | the twin from a chase camera: the CAD robot driving the aisle, cones on the side it treats |
| top right | **CAMERA / AI SUBSYSTEM**: the frame the CropSCOUT pipeline classified (real leaf photo, mast frame or webcam) with the repo's own `live_detect.draw()` HUD — diagnosis, confidence, margins, `SPRAY xx%` line; a thumbnail of the mast camera |
| right | **DECISION**: plant, side, diagnosis, dose, heads, pump seconds, product, severity, image source |
| bottom | **IoT TELEMETRY**: tank (5 gal) gauge, pump, six valve LEDs (L24…R60), spray used vs blanket with savings, inspected/sprayed counts, row map with per-plant status, message counter |

Keys: `q` quit, `space` pause, `s` snapshot. `--record out/demo.mp4 --frames 400` writes a video instead of a window.
With the CropSCOUT repo + models present it uses them (`--source photos|sim|webcam`); otherwise it falls back to the
sim's own labels and says so.

### IoT bus

`iot_bus.py` publishes JSON on `cropscout/a08/telemetry` (~10 Hz: x, speed, tank, pump, valves),
`cropscout/a08/inspection` (per plant: label, diagnosis, confidence, severity, dose, heads, image),
`cropscout/a08/spray` (per valve opening) and `cropscout/a08/mission` (start / summary). Everything is appended to
`out/telemetry.jsonl`; add `--mqtt test.mosquitto.org` (or any broker, `pip install paho-mqtt`) and the same messages
go out over MQTT — subscribe with `mosquitto_sub -h test.mosquitto.org -t "cropscout/a08/#"`. On the real A08 the
Jetson publishes the same topics, so Mission Control and the farmer app need no changes.

## Fastest: double-click

0. `7_MISSION_CONTROL.bat` — the integrated demo (see above).
1. `1_SETUP_AND_OPEN_IN_VSCODE.bat` — creates `.venv`, installs everything, fetches the CropSCOUT models,
   opens `greenhouse_sim.code-workspace` in VS Code. Press **F5** there.
2. `2_RUN_LIVE_VIEWER.bat` — the MuJoCo viewer without VS Code.
3. `3_RUN_WITH_CROPSCOUT_MODELS.bat` — your ONNX models decide (a PlantVillage photo per plant).
4. `4_RUN_LIVE_VIEWER_NO_CAMERA.bat` — fallback if the offscreen cameras upset your GPU driver.
5. `5_FETCH_LEAF_PHOTOS.bat` — downloads PlantVillage leaf photos **including healthy leaves** into
   `leaf_photos\` (healthy plants then get real leaf textures and real photos in photo mode).

The first run builds the leaf textures into `assets\` (about a minute); later runs reuse them.

## The robot is your CAD

`meshes\cad_*.stl` are your SolidWorks export (the per-component STL files on the Desktop), merged into
16 colour groups with the CAD origin restored, so the sim draws the real A08 — tracks, tank, pump, masts,
all six heads, hoses, enclosure, camera mast. The blockout underneath is invisible and only supplies mass
and collision. Nozzle sites, cameras and spray visuals come from `A08_nozzle_positions.csv` and line up with
the brass tips of the export to within 0.1 mm.

Re-exported the assembly? Put the new `CropSCOUT_Robot_A08_... - <component>.STL` files on the Desktop
(File > Save As > STL, binary, "Save all components of an assembly in a single file" OFF) and run
`.venv\Scripts\python.exe split_cad_export.py` — or export a single STL and drop it in `meshes\` as
`cropscout_full.stl` (one colour). `6_EXPORT_CAD_FROM_SOLIDWORKS.bat` can do a single-file export through
the SolidWorks API. Any unit, ASCII or binary, translated-to-positive or not: the loader fixes all of these.

## Cameras

| camera | where | used for |
| --- | --- | --- |
| `eye_front` | the CAD stereo camera on the front mast, forward-facing | row view |
| `eye_left`, `eye_right` | on each spray mast at 0.85 m, looking outwards (**proposed addition**, not in the CAD) | per-plant inspection; what CropSCOUT sees in `--source sim` |
| `overview`, `top`, `aisle` | scene cameras | hero image / GIF |

The README of the CAD package notes that foliage visibility to both sides has not been validated with the
low front camera — the side cameras are the sim's suggestion for that.

## Run configurations (VS Code Run and Debug dropdown)

| config | what happens |
| --- | --- |
| Live viewer (interactive) | sim ground-truth labels decide; 30 mL protectant dose scaled by the heads opened |
| Live viewer + CropSCOUT models (photos per plant) | each plant gets a PlantVillage photo of its own disease class (healthy plants: healthy photos once fetched); crop-view gate + condition classifier + spray rules decide |
| Live viewer + CropSCOUT models (webcam at each stop) | hold a real leaf up to the webcam when the robot stops |
| Render hero image + GIF (headless) | `out/greenhouse_hero.png`, `greenhouse_sweep.gif`, `mission_log.json`, `greenhouse_demo.xml` |
| Render … + CropSCOUT (headless) | same, with the models deciding |
| Live viewer (no camera) | no offscreen rendering |

`--source sim` sends the mast-camera frame itself to the models. Diseased plants carry real PlantVillage
leaflet textures, so the frame is closer to the training photos than a plain render, but it is still a
mixed scene (several leaves, fruit, gutters) and the identity gate may abstain — that is a result, not a bug.

## Files

| file | what it does |
| --- | --- |
| `cropscout_robot.py` | the A08 robot MJCF from the CAD numbers + optional STL skin; nozzle sites from the CSV; cameras |
| `greenhouse_scene.py` | greenhouse structure, 4 rows of plants (textured leaf meshes, fruit trusses), `Greenhouse` API |
| `leaf_assets.py` | builds leaf textures/meshes: procedural compound leaves + keyed-out PlantVillage leaflets |
| `perception.py` | `EyeCamera` (RGB / depth / segmentation + pixel→3D), `detect_ground_truth()` |
| `mission.py` | drive, look left/right, policy, valves by height, pesticide summary |
| `cropscout_bridge.py` | imports the CropSCOUT repo's `Pipeline` + `spray` rules; photo / sim / webcam sources |
| `mission_control.py` | the one-window demo: twin + camera/AI panel + decision + IoT telemetry |
| `iot_bus.py` | JSON telemetry topics, JSONL log, optional MQTT |
| `live_viewer.py`, `render_demo.py` | plain MuJoCo viewer / headless hero image + GIF |
| `fetch_leaf_photos.py` | PlantVillage photos per class into `leaf_photos/` |

## The policy is the one function to replace

`Mission` calls `policy(plant, detections, mission) -> dict(spray, dose_ml, heads, label, ...)` once per plant
and side. `mission.ground_truth_policy` and `cropscout_bridge.CropScoutPolicy` are provided. A Claude tool-use
policy has the same shape: send the mast frame + CropSCOUT's verdict to the API with tools `spray(dose_ml,
heads)`, `skip()`, `flag_for_human(reason)` and return its choice.

## Numbers

`Mission.summary()` compares blanket spraying (every plant × `blanket_dose_ml`, default 30 mL — the
protectant-fungicide rate in your spray rules) with the doses actually applied (rule dose × severity
multiplier × share of heads opened). Pump rate 10 mL/s from the rules. Placeholder rates, as your
`spray-rules.json` says.
