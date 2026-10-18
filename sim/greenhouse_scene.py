"""
A Venlo-style tomato greenhouse (high-wire crop on hanging gutters) + the CropSCOUT A08 robot.

    from greenhouse_scene import Greenhouse
    gh = Greenhouse()              # builds leaf/fruit assets (first run), the MJCF and the model
    gh.save_xml("out/greenhouse_demo.xml")

Layout (metres, MuJoCo frame x forward / y left / z up):
    4 plant rows along x at y = -2.4, -0.8, +0.8, +2.4 ; the robot drives the aisle at y = 0
    gutters at 0.55 m, stems to ~2.6 m, crop wire at 3.2 m, roof gutters at 4.5 m
    the two rows next to the aisle are the mission rows (left = +y, right = -y)
Plants: textured leaf meshes (procedural healthy compound leaves; real PlantVillage leaflets on
diseased plants, see leaf_assets.py), fruit trusses, stems + trellis strings.
"""
import math
import os
import random
from pathlib import Path

import mujoco
import numpy as np

from cropscout_robot import robot_xml, nozzles_mj
from leaf_assets import build_assets, mjcf_assets

HERE = Path(__file__).resolve().parent
ASSET_DIR = HERE / "assets"

ROW_LEN = 8.0
ROW_YS = (-2.4, -0.8, 0.8, 2.4)
MISSION_ROWS = (-0.8, 0.8)
SPACING = 0.5
GUTTER_Z = 0.55
DISEASE_RATE = 0.3
LEAF_LEN = 0.40


def _quat_from_axes(fwd, up):
    """Quaternion (w x y z) of the frame whose local +y is `fwd` and local +z is `up`."""
    y = np.asarray(fwd, float); y /= np.linalg.norm(y)
    z = np.asarray(up, float); z = z - y * (z @ y); z /= np.linalg.norm(z)
    x = np.cross(y, z)
    R = np.stack([x, y, z], axis=1)
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, R.flatten())
    return " ".join(f"{v:.5f}" for v in q)


def _lookat_xyaxes(pos, target):
    f = np.array(target, float) - np.array(pos, float); f /= np.linalg.norm(f)
    z = -f
    x = np.cross([0, 0, 1], z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return " ".join(f"{v:.4f}" for v in np.concatenate([x, y]))


# ----------------------------------------------------------------------------- plants
def _plant_xml(pid, x, y, diseased, cls, assets, rng, rich=True):
    """One high-wire tomato plant. Leaf geoms: p{pid}_leaf{i} (healthy) / p{pid}_leafd{i} (diseased)."""
    toward_aisle = -1.0 if y > 0 else 1.0                      # unit y direction towards the aisle
    h_top = rng.uniform(2.3, 2.7)
    lean = rng.uniform(-0.04, 0.04)
    g = [f'<body name="plant{pid}" pos="{x:.3f} {y:.3f} 0">',
         f'<geom name="p{pid}_slab" type="box" pos="0 0 {GUTTER_Z + 0.04:.3f}" size="0.12 0.09 0.04" rgba="0.93 0.93 0.9 1" contype="0" conaffinity="0"/>',
         f'<geom name="p{pid}_stem" type="cylinder" fromto="0 0 {GUTTER_Z + 0.08:.3f} {lean:.3f} 0 {h_top:.3f}" size="0.011" rgba="0.33 0.45 0.22 1"/>',
         f'<geom name="p{pid}_string" type="cylinder" fromto="{lean:.3f} 0 {h_top:.3f} 0 0 3.2" size="0.0015" rgba="0.95 0.95 0.9 1" contype="0" conaffinity="0"/>']
    n_leaves = rng.randint(17, 21) if rich else rng.randint(11, 13)
    disease_assets = assets["disease"].get(cls) or assets["disease"].get("procedural_blight", [])
    healthy_assets = assets.get("healthy_photos") or assets["healthy"]
    # which leaves are diseased: lower-mid canopy (where the robot's heads and cameras are)
    diseased_idx = set()
    if diseased:
        cand = [i for i in range(n_leaves) if 0.7 + (h_top - 0.9) * i / n_leaves < 1.7]
        diseased_idx = set(rng.sample(cand, min(len(cand), rng.randint(4, 6))))
    for i in range(n_leaves):
        z = 0.72 + (h_top - 0.9) * i / n_leaves + rng.uniform(-0.03, 0.03)
        az = (i * 137.5 + rng.uniform(-25, 25)) * math.pi / 180
        # bias leaves on the mission rows towards the aisle a little (that is where the light is)
        d = np.array([math.cos(az), math.sin(az)])
        d[1] += 0.35 * toward_aisle
        d /= np.linalg.norm(d)
        tilt = rng.uniform(0.35, 0.75)                          # droop below horizontal (rad)
        fwd = np.array([d[0] * math.cos(tilt), d[1] * math.cos(tilt), -math.sin(tilt)])
        up = np.array([0, 0, 1.0]) + np.array([d[0], d[1], 0]) * rng.uniform(-0.3, 0.3)
        q = _quat_from_axes(fwd, up)
        base = np.array([lean * (z / h_top), 0, 0]) + np.array([d[0], d[1], 0]) * 0.012
        if i in diseased_idx and disease_assets:
            a = rng.choice(disease_assets); name = f"p{pid}_leafd{i}"
        else:
            a = rng.choice(healthy_assets); name = f"p{pid}_leaf{i}"
        g.append(f'<geom name="{name}" type="mesh" mesh="{a.name}" material="mat_{a.name}" '
                 f'pos="{base[0]:.3f} {base[1]:.3f} {z:.3f}" quat="{q}" contype="0" conaffinity="0"/>')
        # petiole
        tip = base + fwd * 0.06
        g.append(f'<geom type="capsule" fromto="{base[0]:.3f} {base[1]:.3f} {z:.3f} {tip[0]:.3f} {tip[1]:.3f} {z + fwd[2]*0.06:.3f}" '
                 f'size="0.005" rgba="0.35 0.5 0.25 1" contype="0" conaffinity="0"/>')
    # fruit trusses: low = ripe, mid = turning, high = green
    fi = 0
    for k, (zt, ripe_p) in enumerate([(0.95, 0.95), (1.35, 0.5), (1.75, 0.05)]):
        if not rich and k == 2:
            break
        az = rng.uniform(0, 2 * math.pi)
        d = np.array([math.cos(az), math.sin(az)]); d[1] += 0.4 * toward_aisle; d /= np.linalg.norm(d)
        p0 = np.array([lean * (zt / h_top), 0, zt + rng.uniform(-0.05, 0.05)])
        p1 = p0 + np.array([d[0] * 0.14, d[1] * 0.14, -0.06])
        g.append(f'<geom type="capsule" fromto="{p0[0]:.3f} {p0[1]:.3f} {p0[2]:.3f} {p1[0]:.3f} {p1[1]:.3f} {p1[2]:.3f}" '
                 f'size="0.006" rgba="0.4 0.55 0.28 1" contype="0" conaffinity="0"/>')
        for j in range(rng.randint(4, 6)):
            t = (j + 1) / 6
            c = p0 + (p1 - p0) * t + np.array([rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), -0.045 - 0.02 * (j % 2)])
            r = rng.uniform(0.028, 0.038)
            ripe = rng.random() < ripe_p
            mat = "mat_fruit_red" if ripe else ("mat_fruit_orange" if rng.random() < 0.3 else "mat_fruit_green")
            g.append(f'<geom name="p{pid}_fruit{fi}" type="sphere" pos="{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}" size="{r:.3f}" '
                     f'material="{mat}" contype="0" conaffinity="0"/>')
            g.append(f'<geom type="sphere" pos="{c[0]:.3f} {c[1]:.3f} {c[2] + r*0.9:.3f}" size="{r*0.3:.3f}" '
                     f'rgba="0.35 0.55 0.25 1" contype="0" conaffinity="0"/>')
            fi += 1
    g.append("</body>")
    return "\n".join(g)


# ----------------------------------------------------------------------------- structure
def _structure_xml():
    s = []
    glass = 'material="mat_glass" contype="0" conaffinity="0"'
    steel = 'rgba="0.82 0.83 0.85 1" contype="0" conaffinity="0"'
    x0, x1 = -1.0, ROW_LEN + 1.0
    xm = (x0 + x1) / 2
    for y in (-4.0, 0.0, 4.0):
        s.append(f'<geom type="box" pos="{xm:.2f} {y} 4.5" size="{(x1-x0)/2:.2f} 0.08 0.06" {steel}/>')      # roof gutter
        for x in (x0, xm, x1):
            if y != 0.0:                                                                                     # no columns in the aisle
                s.append(f'<geom type="box" pos="{x:.2f} {y} 2.25" size="0.05 0.05 2.25" {steel}/>')           # column
    for x in (x0, xm, x1):
        s.append(f'<geom type="box" pos="{x:.2f} 0 4.35" size="0.03 4.0 0.12" {steel}/>')                      # truss
    for ridge in (-2.0, 2.0):                                                                               # roof panes
        for side in (-1, 1):
            yc = ridge + side * 1.0
            ang = -side * math.degrees(math.atan2(0.8, 2.0))
            s.append(f'<geom type="box" pos="{xm:.2f} {yc:.2f} 4.9" size="{(x1-x0)/2:.2f} 1.08 0.01" euler="{ang:.1f} 0 0" {glass}/>')
        s.append(f'<geom type="box" pos="{xm:.2f} {ridge} 5.32" size="{(x1-x0)/2:.2f} 0.03 0.03" {steel}/>')
    for y in (-4.0, 4.0):                                                                                   # side walls
        s.append(f'<geom type="box" pos="{xm:.2f} {y} 2.25" size="{(x1-x0)/2:.2f} 0.01 2.25" {glass}/>')
    for y in ROW_YS:                                                                                        # crop + gutter wires
        s.append(f'<geom type="cylinder" fromto="{x0} {y} 3.2 {x1} {y} 3.2" size="0.004" rgba="0.3 0.3 0.3 1" contype="0" conaffinity="0"/>')
        s.append(f'<geom type="box" pos="{xm:.2f} {y} {GUTTER_Z - 0.06:.2f}" size="{ROW_LEN/2 + 0.3:.2f} 0.13 0.06" rgba="0.9 0.9 0.88 1"/>')
        for x in np.arange(x0 + 0.5, x1, 2.0):
            s.append(f'<geom type="cylinder" fromto="{x:.2f} {y} {GUTTER_Z:.2f} {x:.2f} {y} 4.4" size="0.003" rgba="0.5 0.5 0.5 1" contype="0" conaffinity="0"/>')
        for x in np.arange(x0 + 0.25, x1, 1.0):                                                           # gutter stands on the floor
            for dy in (-0.11, 0.11):
                s.append(f'<geom type="cylinder" fromto="{x:.2f} {y + dy:.2f} 0 {x:.2f} {y + dy:.2f} {GUTTER_Z - 0.12:.2f}" size="0.016" rgba="0.55 0.56 0.58 1" contype="0" conaffinity="0"/>')
            s.append(f'<geom type="box" pos="{x:.2f} {y} {GUTTER_Z - 0.13:.2f}" size="0.02 0.15 0.012" rgba="0.55 0.56 0.58 1" contype="0" conaffinity="0"/>')
            s.append(f'<geom type="box" pos="{x:.2f} {y} 0.012" size="0.03 0.16 0.012" rgba="0.5 0.5 0.52 1" contype="0" conaffinity="0"/>')
        for dy in (-0.22, 0.22):                                                                           # grow / heating pipes
            s.append(f'<geom type="cylinder" fromto="{x0} {y + dy:.2f} 0.08 {x1} {y + dy:.2f} 0.08" size="0.025" rgba="0.75 0.76 0.78 1"/>')
    s.append(f'<geom name="aisle" type="box" pos="{xm:.2f} 0 0.004" size="{(x1-x0)/2:.2f} 0.65 0.004" material="mat_path"/>')
    return "\n".join(s)


# ----------------------------------------------------------------------------- scene
def build_xml(seed=3, assets=None):
    rng = random.Random(seed)
    assets = assets or build_assets(ASSET_DIR)
    classes = [c for c in assets["disease"] if c.startswith("Tomato___")] or ["procedural_blight"]
    plants, pid = [], 0
    for y in ROW_YS:
        for x in np.arange(0.5, ROW_LEN, SPACING):
            diseased = rng.random() < DISEASE_RATE
            cls = rng.choice(classes) if diseased else None
            plants.append((pid, float(x), float(y), diseased, cls, y in MISSION_ROWS))
            pid += 1
    plant_blocks = "\n".join(_plant_xml(p[0], p[1], p[2], p[3], p[4], assets, rng, rich=p[5]) for p in plants)
    robot_body, cad_asset, actuators = robot_xml(ROW_LEN)
    cams = [
        f'<camera name="overview" pos="-2.6 -3.4 2.6" xyaxes="{_lookat_xyaxes([-2.6, -3.4, 2.6], [3.0, 0.0, 1.0])}"/>',
        f'<camera name="top" pos="{ROW_LEN/2:.1f} 0 4.25" xyaxes="0 1 0 -1 0 0" fovy="85"/>',
        f'<camera name="aisle" pos="-2.2 0 0.9" xyaxes="0 -1 0 0 0 1" fovy="60"/>',
    ]
    xml = f"""
<mujoco model="cropscout_greenhouse">
  <compiler angle="degree" meshdir="{ASSET_DIR.as_posix()}" texturedir="{ASSET_DIR.as_posix()}"/>
  <option timestep="0.002"/>
  <visual>
    <global offwidth="1280" offheight="720"/>
    <headlight ambient="0.42 0.42 0.42" diffuse="0.45 0.45 0.45" specular="0.1 0.1 0.1"/>
    <quality shadowsize="8192"/>
    <map znear="0.02" zfar="60"/>
  </visual>
  <asset>
    <texture name="sky" type="skybox" builtin="gradient" rgb1="0.80 0.88 0.97" rgb2="0.97 0.98 1" width="256" height="256"/>
    <texture name="floor_tex" type="2d" builtin="checker" rgb1="0.93 0.93 0.91" rgb2="0.88 0.88 0.86" width="512" height="512"/>
    <material name="mat_floor" texture="floor_tex" texrepeat="40 40" reflectance="0.08"/>
    <texture name="path_tex" type="2d" builtin="flat" rgb1="0.62 0.62 0.6" width="64" height="64"/>
    <material name="mat_path" texture="path_tex" reflectance="0.02"/>
    <material name="mat_glass" rgba="0.85 0.93 1 0.28" specular="0.6" shininess="0.6"/>
    <material name="mat_fruit_red" rgba="0.86 0.13 0.08 1" specular="0.55" shininess="0.5"/>
    <material name="mat_fruit_orange" rgba="0.92 0.45 0.1 1" specular="0.5" shininess="0.45"/>
    <material name="mat_fruit_green" rgba="0.55 0.72 0.3 1" specular="0.35" shininess="0.3"/>
    {mjcf_assets(assets)}
    {cad_asset}
  </asset>
  <worldbody>
    <light pos="4 0 6" dir="0 0 -1" diffuse="0.55 0.55 0.55" specular="0.2 0.2 0.2" castshadow="true"/>
    <light pos="-2 -4 4" dir="0.5 0.6 -0.6" diffuse="0.3 0.3 0.3" castshadow="false"/>
    <geom name="floor" type="plane" size="15 10 0.1" material="mat_floor"/>
    {_structure_xml()}
    {chr(10).join(cams)}
    {plant_blocks}
    {robot_body}
  </worldbody>
  <actuator>
    {actuators}
  </actuator>
</mujoco>
"""
    return xml, plants


class Greenhouse:
    def __init__(self, seed=3):
        self.assets = build_assets(ASSET_DIR)
        self.xml, self.plants = build_xml(seed, self.assets)
        self.mission_plants = [p for p in self.plants if p[5]]
        self.model = m = mujoco.MjModel.from_xml_string(self.xml)
        self.data = d = mujoco.MjData(m)
        self.qadr = {"drive_x": m.joint("drive_x").qposadr[0]}
        self.geom_names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or "" for i in range(m.ngeom)]
        self.nozzles = nozzles_mj()
        self.spray_ids = {}
        for (name, side, p, dy, h) in self.nozzles:
            self.spray_ids.setdefault(side, []).append([m.geom(f"{name}_spray{k}").id for k in range(7)])
        self.base_body = m.body("base").id
        mujoco.mj_forward(m, d)

    def save_xml(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(self.xml)

    # --- plants
    def plant_geoms(self, pid, kind="fruit"):
        pre = f"p{pid}_{kind}"
        return [i for i, n in enumerate(self.geom_names) if n.startswith(pre)]

    def plant_target(self, plant):
        ids = self.plant_geoms(plant[0], "fruit")
        if not ids:
            return np.array([plant[1], plant[2], 1.0])
        return np.mean([self.data.geom_xpos[i] for i in ids], axis=0)

    def geom_plant(self, geom_id):
        n = self.geom_names[geom_id]
        if n.startswith("p") and "_" in n and n[1:n.index("_")].isdigit():
            return int(n[1:n.index("_")])
        return None

    # --- robot
    def set_pose(self, x, q=None):
        """Kinematic: put the robot at x along the aisle (q kept for API compatibility)."""
        self.data.qpos[self.qadr["drive_x"]] = x
        self.data.ctrl[0] = x
        mujoco.mj_forward(self.model, self.data)

    def set_spray(self, side, on, heads=(0, 1, 2)):
        """Open/close the spray visual of `side` ('left' = +y row, 'right' = -y row) for head indices (0=24in,1=42in,2=60in)."""
        for k, ids in enumerate(self.spray_ids[side]):
            a = 0.3 if (on and k in heads) else 0.0
            for g in ids:
                self.model.geom_rgba[g, 3] = a

    def set_spray_all(self, on):
        for side in self.spray_ids:
            self.set_spray(side, on)

    def nozzle_pos(self, side, head=1):
        name = [n for n in self.nozzles if n[1] == side][head][0]
        return self.data.site(name).xpos.copy()

    def line_of_sight(self, target, side=None, head=1):
        """Ray from the side's middle nozzle to the target: (distance_m, first_geom_id)."""
        if side is None:
            side = "left" if target[1] > 0 else "right"
        tip = self.nozzle_pos(side, head)
        vec = np.asarray(target, float) - tip
        vec = vec / np.linalg.norm(vec)
        geomid = np.array([-1], dtype=np.int32)
        groups = np.array([1, 1, 0, 1, 1, 1], dtype=np.uint8)
        dist = mujoco.mj_ray(self.model, self.data, tip, vec, groups, 1, self.base_body, geomid)
        return dist, int(geomid[0])

    def scene_option_no_spray(self):
        opt = mujoco.MjvOption()
        opt.geomgroup[2] = 0
        return opt


if __name__ == "__main__":
    gh = Greenhouse()
    gh.save_xml("out/greenhouse_demo.xml")
    print(f"{gh.model.ngeom} geoms, {len(gh.plants)} plants ({len(gh.mission_plants)} on the mission rows), "
          f"{sum(p[3] for p in gh.mission_plants)} flagged on mission rows")
