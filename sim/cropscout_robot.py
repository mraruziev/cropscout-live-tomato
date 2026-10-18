"""
CropSCOUT Robot A08 "Raised Side Spray" for MuJoCo, built from the SolidWorks package's own
documentation (README_A08.txt, EDITING_GUIDE_A08.txt, A08_nozzle_positions.csv, BOM descriptions):

  main assembly axes  X forward, Y up, Z lateral, mm, ground at Y0
  tracked base        two flat rubber tracks 1520 mm loop x 100 mm wide, outboard rails X -345..335
  frame / deck        24x12 in welded tube core, 28x14 in steel deck (top ~280 mm)
  tank                5 US gal FastRack jug 254 x 254 x 305 mm on the deck
  pump                Pumpoasis 12 V 2.5 GPM, rear wet bay
  electronics         Jetson Orin Nano enclosure, E-stop, front camera mast (stereo camera 90x30x28, faces +X)
  twin mast           two 40x40x2 mm uprights, 1270 mm, at X180 Z+/-155 on 120x70 feet, cross tie at Y~520
  six spray heads     brass side-spray tips at X180, Z+/-278, heights 609.6 / 1066.8 / 1524 mm, flow +/-Z

MuJoCo frame: x forward, y left, z up (metres)  ->  mj = (X, -Z, Y) / 1000.

If you export the assembly from SolidWorks as ONE binary STL (File > Save As > STL, options:
"Save all components of an assembly in a single file" ON, "Do not translate STL output data to
positive space" ON, unit millimetres, resolution Coarse) and drop it in  meshes/cropscout_full.stl ,
the real CAD skin is drawn on top and the blockout parts become invisible collision/inertia bodies.
Extra per-part STLs are optional; the kinematics stay the same (the heads are fixed-height mates).
"""
import csv
import re
import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MESH_DIR = HERE / "meshes"
NOZZLE_CSV = HERE / "A08_nozzle_positions.csv"

# ----------------------------------------------------------------------------- CAD numbers (mm)
DECK_TOP = 280.0
TRACK_Z = 240.0          # lateral centre of each track
TRACK_LEN, TRACK_W, TRACK_H = 700.0, 100.0, 116.0
MAST_X, MAST_Z, MAST_LEN, MAST_SEC = 180.0, 155.0, 1270.0, 40.0
CROSS_TIE_Y = 520.0
CAM_FRONT = (310.0, 500.0, 0.0)          # stereo camera envelope centre (X, Y, Z) - low, forward-facing
SIDE_CAM_Y = 850.0                       # (proposed addition) side cameras on the masts, not in the CAD

# colours for the CAD export groups (meshes/cad_<group>.stl, made by split_cad_export.py) and for
# SolidWorks' one-file-per-component export (matched against the component file name)
CAD_COLOURS = {
    "track": "0.06 0.06 0.06 1", "tank": "0.95 0.94 0.9 1", "pump_head": "0.78 0.08 0.08 1",
    "diaphragm": "0.78 0.08 0.08 1", "pump": "0.22 0.22 0.24 1", "hose": "0.2 0.18 0.8 1",
    "route": "0.2 0.18 0.8 1", "inlet_tube": "0.2 0.18 0.8 1", "estop": "0.85 0.05 0.05 1",
    "coil_cap": "0.1 0.3 0.85 1", "brass": "0.75 0.6 0.2 1", "mast": "0.62 0.64 0.68 1",
    "spray_head": "0.22 0.22 0.25 1", "carriage": "0.22 0.22 0.25 1", "solenoid": "0.22 0.22 0.25 1",
    "camera": "0.12 0.12 0.14 1", "stereo": "0.12 0.12 0.14 1", "electronics": "0.2 0.2 0.22 1",
    "jetson": "0.1 0.35 0.15 1", "pcb": "0.1 0.35 0.15 1", "drive": "0.3 0.3 0.33 1",
    "sprocket": "0.3 0.3 0.33 1", "wheel": "0.3 0.3 0.33 1", "rail": "0.3 0.3 0.33 1",
    "motor": "0.28 0.28 0.3 1", "my1016z": "0.28 0.28 0.3 1", "chassis": "0.08 0.08 0.09 1",
}

DEFAULT_NOZZLES = [  # (x_mm, height_mm, lateral_z_mm, flow_z, height_in)
    (180, 609.6, -278, -1, 24), (180, 1066.8, -278, -1, 42), (180, 1524, -278, -1, 60),
    (180, 609.6, 278, 1, 24), (180, 1066.8, 278, 1, 42), (180, 1524, 278, 1, 60),
]


def mj(x, y, z):
    """CAD (X fwd, Y up, Z right) mm -> MuJoCo (x fwd, y left, z up) m, as a string."""
    return f"{x/1000:.4f} {-z/1000:.4f} {y/1000:.4f}"


def mjv(x, y, z):
    return np.array([x / 1000, -z / 1000, y / 1000])


def load_nozzles(path=NOZZLE_CSV):
    """Nozzle tips from A08_nozzle_positions.csv (falls back to the documented defaults)."""
    if not Path(path).exists():
        return DEFAULT_NOZZLES
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out.append((float(r["x_mm"]), float(r["height_mm"]), float(r["lateral_z_mm"]),
                        float(r["flow_z"]), float(r["height_in"])))
    return sorted(out, key=lambda t: (t[2] > 0, t[1]))


def nozzles_mj():
    """[(name, side, xyz_m, dir_y, height_m)] : side 'left' = CAD -Z (MuJoCo +y)."""
    out = []
    for (x, h, z, fz, hin) in load_nozzles():
        side = "left" if z < 0 else "right"
        out.append((f"nozzle_{side}_{int(hin)}", side, mjv(x, h, z), -fz, h / 1000))
    return out


# ----------------------------------------------------------------------------- STL helpers
def stl_bounds(path):
    """Min/max corner of a binary or ASCII STL (mm as exported)."""
    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        pts = []
        for line in data.decode(errors="ignore").splitlines():
            s = line.strip()
            if s.startswith("vertex"):
                pts.append([float(v) for v in s.split()[1:4]])
        arr = np.array(pts)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        tri = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
        arr = tri["v"].reshape(-1, 3)
    return arr.min(axis=0), arr.max(axis=0)


def _binary_stl(path):
    """MuJoCo reads binary STL only: convert an ASCII export once (cached as <name>.bin.stl)."""
    data = Path(path).read_bytes()
    if not (data[:5] == b"solid" and b"facet" in data[:400]):
        return Path(path)
    out = Path(path).with_suffix(".bin.stl")
    if out.exists() and out.stat().st_mtime >= Path(path).stat().st_mtime:
        return out
    pts = [[float(v) for v in line.split()[1:4]] for line in data.decode(errors="ignore").splitlines()
           if line.strip().startswith("vertex")]
    arr = np.asarray(pts, np.float32).reshape(-1, 3, 3)
    with open(out, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(arr)))
        rec = np.zeros(len(arr), dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
        rec["v"] = arr.reshape(-1, 9)
        f.write(rec.tobytes())
    return out


def cad_files():
    """meshes/cropscout_full.stl, or every *.stl in meshes/ (SolidWorks' one-file-per-component export)."""
    if not MESH_DIR.exists():
        return []
    one = MESH_DIR / "cropscout_full.stl"
    files = [one] if one.exists() else sorted(p for p in MESH_DIR.glob("*.stl") if not p.name.endswith(".bin.stl"))
    return [_binary_stl(f) for f in files]


def cad_mesh_xml():
    """Asset + geom XML for the exported CAD (any unit, origin kept or not), else ('', '')."""
    files = cad_files()
    if not files:
        return "", ""
    bounds = [stl_bounds(f) for f in files]
    lo = np.min([b[0] for b in bounds], axis=0)
    hi = np.max([b[1] for b in bounds], axis=0)
    height = hi[1] - lo[1]                                   # CAD Y is up: the robot is ~1.55 m tall
    if 0.6 < height < 3.0:
        unit = 1.0                                           # metres
    elif 25 < height < 120:
        unit = 0.0254                                        # inches (the document's display unit)
    else:
        unit = 0.001                                         # millimetres
    # SolidWorks translates STL output to positive space unless told not to: undo that if it happened
    lo_mm, hi_mm = lo * unit * 1000, hi * unit * 1000
    offset = np.zeros(3)
    if lo_mm[1] > 20 or abs((lo_mm[0] + hi_mm[0]) / 2) > 120 or abs((lo_mm[2] + hi_mm[2]) / 2) > 120:
        offset = np.array([-(lo_mm[0] + hi_mm[0]) / 2 + 5, -lo_mm[1], -(lo_mm[2] + hi_mm[2]) / 2])
    assets, geoms = [], []
    for i, f in enumerate(files):
        stem = f.name.lower().replace(".bin.stl", "").replace(".stl", "")
        name = "cad_full" if len(files) == 1 else f"cad_{i}_{re.sub(r'[^a-z0-9]+', '_', stem)[:40]}"
        rgba = next((c for key, c in CAD_COLOURS.items() if key in stem), "0.78 0.78 0.8 1")
        assets.append(f'<mesh name="{name}" file="{f.as_posix()}" scale="{unit} {unit} {unit}"/>')
        geoms.append(f'<geom name="{name}" type="mesh" mesh="{name}" pos="{mj(*offset)}" euler="90 0 0" '
                     f'rgba="{rgba}" contype="0" conaffinity="0" group="0" density="0"/>')
    print(f"[cad] {len(files)} STL file(s), height {height * unit:.2f} m -> unit scale {unit}, "
          f"origin shift {np.round(offset, 1)} mm")
    return "\n".join(assets), "\n".join(geoms)


# ----------------------------------------------------------------------------- robot MJCF
def robot_xml(row_len, with_cad=True):
    """<body name='base'> ... </body> plus (asset_xml, actuator_xml)."""
    cad_asset, cad_geom = cad_mesh_xml() if with_cad else ("", "")
    g = 3 if cad_geom else 0                     # blockout visuals hidden when the CAD skin is present
    B = f'group="{g}"'
    parts = []

    def box(name, cx, cy, cz, sx, sy, sz, rgba, mass=None, **kw):
        extra = " ".join(f'{k}="{v}"' for k, v in kw.items())
        m = f'mass="{mass}"' if mass else ""
        parts.append(f'<geom name="{name}" type="box" pos="{mj(cx, cy, cz)}" size="{sx/2000:.4f} {sy/2000:.4f} {sz/2000:.4f}" '
                     f'rgba="{rgba}" {B} {m} {extra}/>')

    def cyl(name, p0, p1, r, rgba, mass=None, **kw):
        extra = " ".join(f'{k}="{v}"' for k, v in kw.items())
        m = f'mass="{mass}"' if mass else ""
        parts.append(f'<geom name="{name}" type="cylinder" fromto="{mj(*p0)} {mj(*p1)}" size="{r/1000:.4f}" '
                     f'rgba="{rgba}" {B} {m} {extra}/>')

    dark = "0.07 0.07 0.08 1"; steel = "0.3 0.3 0.32 1"; alu = "0.62 0.64 0.68 1"; hose = "0.22 0.2 0.8 1"
    # tracks + drive
    for s in (-1, 1):
        z = s * TRACK_Z
        box(f"track_{'r' if s>0 else 'l'}", -5, TRACK_H / 2, z, TRACK_LEN, TRACK_W, TRACK_H, "0.08 0.08 0.08 1", mass=9)
        for xe in (-300, 290):
            cyl(f"sprocket_{'r' if s>0 else 'l'}_{xe}", (xe, 58, z - 52), (xe, 58, z + 52), 48, "0.2 0.2 0.22 1",
                contype="0", conaffinity="0")
        cyl(f"motor_{'r' if s>0 else 'l'}", (-300, 70, z - s * 60), (-300, 70, z - s * 175), 48, "0.3 0.3 0.32 1",
            mass=3, contype="0", conaffinity="0")
    # frame, side panels, deck, noses, bumper
    box("tube_core", 0, 200, 0, 610, 305, 32, steel, mass=12)
    box("skin_l", 0, 200, -195, 660, 2, 150, dark); box("skin_r", 0, 200, 195, 660, 2, 150, dark)
    box("deck", 0, DECK_TOP - 2.4, 0, 711, 356, 4.8, "0.35 0.36 0.38 1", mass=14)
    box("front_nose", 330, 190, 0, 70, 300, 130, dark); box("rear_nose", -330, 190, 0, 70, 300, 130, dark)
    cyl("bumper", (380, 180, -180), (380, 180, 180), 10, "0.8 0.8 0.82 1", contype="0", conaffinity="0")
    box("battery", -40, 160, 0, 250, 205, 70, "0.15 0.15 0.18 1", mass=6, contype="0", conaffinity="0")
    # tank + cradle + pump
    box("tank", -60, DECK_TOP + 20 + 152, 0, 254, 254, 305, "0.95 0.94 0.9 1", mass=20)
    for yb in (DECK_TOP + 20 + 100, DECK_TOP + 20 + 200):
        box(f"tank_band{int(yb)}", -60, yb, 0, 258, 258, 8, "0.8 0.8 0.78 1", contype="0", conaffinity="0")
    cyl("tank_cap", (-60, DECK_TOP + 325, 0), (-60, DECK_TOP + 350, 0), 35, "0.2 0.2 0.2 1", contype="0", conaffinity="0")
    box("pump_shelf", -290, DECK_TOP + 10, 0, 130, 200, 3, alu, contype="0", conaffinity="0")
    cyl("pump", (-340, DECK_TOP + 60, 0), (-230, DECK_TOP + 60, 0), 40, "0.25 0.25 0.28 1", mass=2, contype="0", conaffinity="0")
    cyl("pump_head", (-300, DECK_TOP + 60, 40), (-300, DECK_TOP + 60, 90), 42, "0.75 0.08 0.08 1", contype="0", conaffinity="0")
    # electronics + camera mast
    box("enclosure", 250, DECK_TOP + 45, 0, 220, 160, 90, "0.2 0.2 0.22 1", mass=2)
    cyl("estop", (300, DECK_TOP + 90, 50), (300, DECK_TOP + 112, 50), 11, "0.85 0.05 0.05 1", contype="0", conaffinity="0")
    box("cam_mast", 300, (DECK_TOP + 90 + CAM_FRONT[1]) / 2, -40, 25.4, 25.4, CAM_FRONT[1] - DECK_TOP - 90, alu,
        contype="0", conaffinity="0")
    box("stereo_cam", CAM_FRONT[0], CAM_FRONT[1], CAM_FRONT[2], 28, 90, 30, "0.12 0.12 0.14 1", contype="0", conaffinity="0")
    # twin mast
    for s in (-1, 1):
        z = s * MAST_Z
        tag = "l" if s < 0 else "r"
        box(f"mast_{tag}", MAST_X, DECK_TOP + 6 + MAST_LEN / 2, z, MAST_SEC, MAST_SEC, MAST_LEN, alu, mass=4)
        box(f"mast_foot_{tag}", MAST_X, DECK_TOP + 3, z, 120, 70, 6, alu, contype="0", conaffinity="0")
        box(f"mast_cap_{tag}", MAST_X, DECK_TOP + 6 + MAST_LEN + 8, z, 44, 44, 16, "0.2 0.2 0.2 1", contype="0", conaffinity="0")
        cyl(f"hose_{tag}", (MAST_X - 35, DECK_TOP + 40, z), (MAST_X - 35, DECK_TOP + MAST_LEN - 40, z), 7,
            hose, contype="0", conaffinity="0")
        # (proposed) side camera on the mast, looking outwards; not part of the CAD package
        box(f"side_cam_{tag}", MAST_X, SIDE_CAM_Y, z + s * 45, 30, 30, 60, "0.12 0.12 0.14 1", contype="0", conaffinity="0")
    box("cross_tie", MAST_X, CROSS_TIE_Y, 0, 20, 40, 2 * MAST_Z - MAST_SEC, alu, contype="0", conaffinity="0")
    cyl("feed_hose", (-230, DECK_TOP + 60, -60), (MAST_X - 35, DECK_TOP + 40, -MAST_Z), 7, hose,
        contype="0", conaffinity="0")
    cyl("feed_hose2", (-230, DECK_TOP + 60, 60), (MAST_X - 35, DECK_TOP + 40, MAST_Z), 7, hose,
        contype="0", conaffinity="0")
    # six spray heads: carriage clamp on the mast, solenoid valve outboard, adapter + brass tip
    sites, cones = [], []
    for (name, side, p, dy, h) in nozzles_mj():
        s = -1 if side == "left" else 1          # CAD Z sign
        z_mast = s * MAST_Z
        hmm = h * 1000
        box(f"{name}_carriage", MAST_X, hmm, z_mast, 60, 50, 60, "0.3 0.3 0.32 1", contype="0", conaffinity="0")
        box(f"{name}_valve", MAST_X, hmm, s * (MAST_Z + 65), 40, 40, 65, "0.25 0.25 0.3 1", contype="0", conaffinity="0")
        cyl(f"{name}_coil", (MAST_X, hmm + 20, s * (MAST_Z + 65)), (MAST_X, hmm + 38, s * (MAST_Z + 65)), 13,
            "0.1 0.3 0.85 1", contype="0", conaffinity="0")
        cyl(f"{name}_adapter", (MAST_X, hmm, s * (MAST_Z + 98)), (MAST_X, hmm, s * 262), 7, "0.8 0.8 0.82 1",
            contype="0", conaffinity="0")
        cyl(f"{name}_tip", (MAST_X, hmm, s * 262), (MAST_X, hmm, s * 278), 6, "0.75 0.6 0.2 1", contype="0", conaffinity="0")
        sites.append(f'<site name="{name}" pos="{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" size="0.004"/>')
        for k in range(7):
            d = 0.05 + 0.06 * k
            cones.append(f'<geom name="{name}_spray{k}" type="sphere" pos="{p[0]:.4f} {p[1] + dy * d:.4f} {p[2]:.4f}" '
                         f'size="{0.015 + 0.02 * k:.3f}" rgba="0.6 0.85 1 0.0" contype="0" conaffinity="0" group="2"/>')
    cams = [
        f'<camera name="eye_front" pos="{mj(CAM_FRONT[0] + 20, CAM_FRONT[1], 0)}" xyaxes="0 -1 0 0 0 1" fovy="60"/>',
        f'<camera name="eye_left" pos="{mj(MAST_X, SIDE_CAM_Y, -(MAST_Z + 80))}" xyaxes="1 0 0 0 0 1" fovy="70"/>',
        f'<camera name="eye_right" pos="{mj(MAST_X, SIDE_CAM_Y, MAST_Z + 80)}" xyaxes="-1 0 0 0 0 1" fovy="70"/>',
    ]
    body = f"""
<body name="base" pos="0 0 0">
  <joint name="drive_x" type="slide" axis="1 0 0" range="-1 {row_len + 1}" damping="60"/>
  {cad_geom}
  {chr(10).join(parts)}
  {chr(10).join(sites)}
  {chr(10).join(cones)}
  {chr(10).join(cams)}
</body>"""
    actuators = f'<position name="a_drive" joint="drive_x" kp="3000" kv="300" ctrlrange="-1 {row_len + 1}"/>'
    return body, cad_asset, actuators


if __name__ == "__main__":
    for n in nozzles_mj():
        print(n[0], n[1], np.round(n[2], 3), "dir_y", n[3])
    print("CAD skin:", "found" if (MESH_DIR / "cropscout_full.stl").exists() else "not found (blockout only)")
