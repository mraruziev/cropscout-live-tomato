"""
Turn SolidWorks' one-STL-per-component export of the A08 assembly into the colour-grouped meshes the
sim draws (meshes/cad_<group>.stl, millimetres, CAD origin restored).

    python split_cad_export.py                       # looks on the Desktop for "CropSCOUT_Robot_A08_* - *.STL"
    python split_cad_export.py C:\\some\\folder       # or any folder with those files

SolidWorks export that produces these files: File > Save As > STL, Options: binary, "Save all components
of an assembly in a single file" OFF. (With it ON you get one file: drop that in meshes/ as
cropscout_full.stl instead - also supported, just without per-part colours.)
"""
import glob
import os
import re
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "meshes"
SKIP = re.compile(r"Washer|Nut|Screw|Spacer|Bearing_6203|Circlip|Thrust|Collar|Grub|Race|Mount_Stack|Clamp_Screw", re.I)
GROUPS = [  # first match wins; colours live in cropscout_robot.CAD_COLOURS
    ("tracks", r"Flat_Rubber_Track"),
    ("tank", r"Tank_FastRack|Tank_70mm_cap|Tank_vent_cap"),
    ("pump_head", r"red_diaphragm_head"),
    ("hoses", r"Pressure_Distribution_Routes|Suction_Route|Pump_inlet_tube|Suction_hose"),
    ("estop", r"Estop"),
    ("coil_caps", r"Blue_Coil_Cap"),
    ("brass_tips", r"Brass_Side_Spray_Tip"),
    ("mast", r"Twin_Mast|Mast_End_Stop_Caps|Mast_Base_M6"),
    ("spray_heads", r"Sliding_Nozzle_Carriage|Solenoid_Valve|Nozzle_Adapter|Valve_Retention"),
    ("camera", r"Camera_mast|Stereo_camera|Camera_lens"),
    ("electronics", r"Electronics_enclosure|Electronics_lid|Lid_gasket|converter|Cable_glands"),
    ("jetson", r"Jetson|Custom_PCB|mounting_plate"),
    ("pump", r"Pumpoasis_12V|Pump_mount_shelf"),
    ("drive", r"Sprocket|Support_Wheel|Support_Axle|Outboard_Rail|Carrier_Rail|Stubshaft|Bearing_Housing|Motor_Mount|Frame_Bracket|Upper_Bridge|Crush_Sleeve"),
    ("motors", r"MY1016Z"),
    ("chassis", r"."),
]


def read_stl(p):
    d = open(p, "rb").read()
    if d[:5] == b"solid" and b"facet" in d[:400]:
        pts = [[float(v) for v in l.split()[1:4]] for l in d.decode(errors="ignore").splitlines()
               if l.strip().startswith("vertex")]
        return np.array(pts, np.float32).reshape(-1, 3, 3)
    n = struct.unpack("<I", d[80:84])[0]
    tri = np.frombuffer(d[84:84 + n * 50], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return tri["v"].reshape(-1, 3, 3).astype(np.float32)


def write_stl(p, tris):
    rec = np.zeros(len(tris), dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    rec["v"] = tris.reshape(-1, 9)
    with open(p, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tris)) + rec.tobytes())


def main(src):
    files = sorted(glob.glob(os.path.join(src, "CropSCOUT_Robot_A08_* - *.STL")) +
                   glob.glob(os.path.join(src, "CropSCOUT_Robot_A08_* - *.stl")))
    if not files:
        sys.exit(f"no 'CropSCOUT_Robot_A08_... - <component>.STL' files in {src}")
    parts = {}
    for f in files:
        name = os.path.basename(f).split(" - ", 1)[1]
        if SKIP.search(name):
            continue
        parts[name] = read_stl(f)
    print(f"{len(files)} files, {len(parts)} parts kept (fasteners skipped)")
    # the exporter translates the assembly to positive space: restore the CAD origin from the twin mast
    # (X centre 180 mm, symmetric about Z=0) and the lowest track point (ground, Y=0)
    mast = next((v for k, v in parts.items() if "Twin_Mast" in k), None)
    tracks = [v for k, v in parts.items() if "Flat_Rubber_Track" in k]
    all_pts = np.concatenate([v.reshape(-1, 3) for v in parts.values()])
    if mast is not None and tracks:
        mlo, mhi = mast.reshape(-1, 3).min(0), mast.reshape(-1, 3).max(0)
        offset = np.array([180.0 - (mlo[0] + mhi[0]) / 2, -min(t.reshape(-1, 3)[:, 1].min() for t in tracks),
                           -(mlo[2] + mhi[2]) / 2])
    else:
        lo, hi = all_pts.min(0), all_pts.max(0)
        offset = np.array([5 - (lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    # inches? (document unit) -> mm
    height = (all_pts[:, 1].max() - all_pts[:, 1].min())
    scale = 25.4 if 25 < height < 120 else 1.0
    print(f"origin shift {np.round(offset, 1)}  unit scale {scale}")
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("cad_*.stl"):
        old.unlink()
    groups = {}
    for name, tris in parts.items():
        for g, pat in GROUPS:
            if re.search(pat, name, re.I):
                groups.setdefault(g, []).append((tris + offset) * scale)
                break
    for g, lst in groups.items():
        t = np.concatenate(lst)
        write_stl(OUT / f"cad_{g}.stl", t)
        print(f"  cad_{g}.stl  {len(t):7d} triangles  ({len(lst)} parts)")
    print(f"wrote {len(groups)} mesh groups to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Desktop"))
