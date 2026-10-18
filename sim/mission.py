"""
The row-scouting mission for the CropSCOUT A08 (raised side spray):
drive the aisle, stop at every plant pair, look left and right with the mast cameras, let a
*policy* decide per plant (spray? which heads? how much?), open that side's valves, log, move on.

    mission = Mission(gh, cams)                      # cams = {"left": EyeCamera, "right": EyeCamera}
    mission = Mission(gh, cams, policy=CropScoutPolicy(...), bus=IoTBus())
    for state in mission: ...
    print(mission.summary())

A policy is any callable  policy(plant, detections, mission) -> dict  with at least
    spray: bool, dose_ml: float, label: str
and optionally heads: tuple of head indices (0 = 24 in, 1 = 42 in, 2 = 60 in) to open, and
    frame: BGR image the decision was made on (shown in Mission Control), hud: dict for the camera HUD.
"""
from collections import Counter

import numpy as np

from greenhouse_scene import ROW_LEN
from perception import detect_ground_truth

HEAD_HEIGHTS = (0.6096, 1.0668, 1.524)        # m, from A08_nozzle_positions.csv
TANK_ML = 18927.0                             # 5 US gal FastRack jug


def heads_for_heights(zs, reach=0.35):
    heads = tuple(k for k, h in enumerate(HEAD_HEIGHTS) if any(abs(z - h) < reach for z in zs))
    return heads or (0, 1, 2)


# ----------------------------------------------------------------------------- default policy
def ground_truth_policy(plant, detections, mission, dose_ml=30.0):
    """Spray the protectant dose when the camera sees 2+ blighted leaves on this plant (sim labels)."""
    own = [d for d in detections
           if (d.plant_id if d.plant_id is not None else
               (mission.nearest_plant(d.xyz) if d.xyz is not None else None)) == plant[0]]
    counts = Counter(d.label for d in own)
    blight = plant[3] if mission.cam is None else counts.get("leaf_blight", 0) >= 2
    zs = [d.xyz[2] for d in own if d.label == "leaf_blight" and d.xyz is not None]
    heads = heads_for_heights(zs) if blight else ()
    dose = dose_ml * len(heads) / 3 if blight else 0.0
    frame = None
    if mission.cam is not None:
        frame = np.ascontiguousarray(mission.cam.rgb()[..., ::-1])
    cls = (plant[4] or "Tomato___Early_blight").replace("Tomato___", "").replace("_", " ") if blight else "healthy"
    hud = dict(status="identified", urgency="routine" if blight else "none",
               line1=f"Tomato leaf: {cls}  {min(99, 60 + 8 * counts.get('leaf_blight', 0))}%" if blight else "Healthy tomato leaf  97%",
               line2=f"Tomato leaf (sim ground-truth labels)   urgency: {'routine' if blight else 'none'}",
               line3=f"{counts.get('leaf_blight', 0)} blighted / {counts.get('leaf_healthy', 0)} healthy leaves, "
                     f"{counts.get('fruit_ripe', 0)} ripe fruit", ms=0.0,
               spray=(f"SPRAY {int(round(100 * dose / 56))}%  ({dose:.0f} mL protectant fungicide, ~{dose / 10:.1f} s pump, "
                      f"heads {heads})" if blight else "SPRAY 0%  Healthy leaf: nothing to treat."))
    return dict(spray=blight, dose_ml=dose, heads=heads,
                label=f"Tomato_leaf_{(plant[4] or 'Tomato___Early_blight').replace('Tomato___', '').lower()}" if blight else "Tomato_leaf_healthy",
                diagnosis=hud["line1"].split("  ")[0], confidence=0.9 if blight else 0.97, severity="medium" if blight else "low",
                fruit_ripe=counts.get("fruit_ripe", 0), fruit_unripe=counts.get("fruit_unripe", 0),
                leaves_blight=counts.get("leaf_blight", 0), leaves_healthy=counts.get("leaf_healthy", 0),
                frame=frame, hud=hud, image="mast camera (sim)")


# ----------------------------------------------------------------------------- mission
class Mission:
    def __init__(self, gh, cams=None, policy=None, detector=detect_ground_truth, bus=None, speed=0.35, dt=0.05,
                 look_time=0.4, pump_ml_per_s=10.0, blanket_dose_ml=30.0, max_spray_s=8.0, tank_ml=TANK_ML):
        self.gh = gh
        self.cams = cams or {}
        self.cam = None
        self.policy = policy or ground_truth_policy
        self.detector = detector
        self.bus = bus
        self.speed, self.dt, self.look_time = speed, dt, look_time
        self.pump, self.blanket_dose, self.max_spray_s = pump_ml_per_s, blanket_dose_ml, max_spray_s
        self.tank_ml, self.tank_full = tank_ml, tank_ml
        self.log = []
        self.sprayed_ml = 0.0
        self.t = 0.0
        self.x = 0.0
        self.valves = [False] * 6                 # left 24/42/60, right 24/42/60
        self.pump_on = False
        self.last_inspection = None               # dict(plant, side, obs, frame)
        self.status = {p[0]: "pending" for p in gh.mission_plants}

    def nearest_plant(self, xyz):
        return min(self.gh.mission_plants, key=lambda p: (xyz[0] - p[1]) ** 2 + (xyz[1] - p[2]) ** 2)[0]

    def _telemetry(self, mode):
        if self.bus is not None:
            self.bus.publish("telemetry", dict(mode=mode, x_m=round(self.x, 3), speed=self.speed if mode == "drive" else 0.0,
                                               tank_ml=round(self.tank_ml), tank_pct=round(100 * self.tank_ml / self.tank_full, 1),
                                               pump_on=self.pump_on, valves=list(self.valves),
                                               mission_time_s=round(self.t, 2)))

    def __iter__(self):
        gh = self.gh
        plants = gh.mission_plants
        stops = sorted({round(p[1], 3) for p in plants})
        self.x = x = stops[0] - 1.2
        i = 0
        gh.set_pose(x)
        if self.bus is not None:
            self.bus.publish("mission", dict(event="start", plants=len(plants), tank_ml=self.tank_ml))
        tick = 0
        while x < ROW_LEN + 0.6:
            if i < len(stops) and x >= stops[i] - 0.18:
                for plant in [p for p in plants if abs(p[1] - stops[i]) < 1e-6]:
                    side = "left" if plant[2] > 0 else "right"
                    self.cam = self.cams.get(side)
                    self.status[plant[0]] = "inspecting"
                    for _ in range(int(self.look_time / self.dt)):
                        yield self._state(x, plant, "look"); self.t += self.dt
                    dets = self.detector(self.cam) if self.cam is not None else []
                    obs = dict(plant=plant[0], x=round(plant[1], 2), side=side, t=round(self.t, 1), truth_class=plant[4])
                    obs.update(self.policy(plant, dets, self))
                    frame, hud = obs.pop("frame", None), obs.pop("hud", None)
                    dist, hit = gh.line_of_sight(gh.plant_target(plant), side)
                    obs["clear_line_of_sight"] = hit >= 0 and gh.geom_plant(hit) == plant[0]
                    self.log.append(obs)
                    self.last_inspection = dict(plant=plant, side=side, obs=obs, frame=frame, hud=hud)
                    self.status[plant[0]] = "spray" if obs.get("spray") else ("flag" if obs.get("action") == "remove" else "healthy")
                    if self.bus is not None:
                        self.bus.publish("inspection", {k: v for k, v in obs.items() if k != "frame"})
                    if obs.get("spray") and obs.get("dose_ml", 0) > 0:
                        heads = tuple(obs.get("heads") or (0, 1, 2))
                        obs["heads"] = heads
                        seconds = min(obs["dose_ml"] / self.pump, self.max_spray_s)
                        obs["spray_seconds"] = round(seconds, 1)
                        self.sprayed_ml += obs["dose_ml"]
                        self.tank_ml = max(0.0, self.tank_ml - obs["dose_ml"])
                        gh.set_spray(side, True, heads)
                        base = 0 if side == "left" else 3
                        self.valves = [False] * 6
                        for h in heads:
                            self.valves[base + h] = True
                        self.pump_on = True
                        if self.bus is not None:
                            self.bus.publish("spray", dict(plant=plant[0], side=side, heads=list(heads), dose_ml=obs["dose_ml"],
                                                           seconds=round(seconds, 1), tank_ml_after=round(self.tank_ml)))
                        for _ in range(int(seconds / self.dt)):
                            yield self._state(x, plant, "spray"); self.t += self.dt
                        gh.set_spray(side, False)
                        self.valves = [False] * 6
                        self.pump_on = False
                        self._telemetry("spray_done")
                i += 1
            yield self._state(x, None, "drive"); self.t += self.dt
            x += self.speed * self.dt
            self.x = x
            gh.set_pose(x)
            tick += 1
            if tick % 2 == 0:
                self._telemetry("drive")
        if self.bus is not None:
            self.bus.publish("mission", dict(event="summary", **self.summary()))

    def _state(self, x, plant, mode):
        return dict(t=self.t, x=x, plant=None if plant is None else plant[0], mode=mode)

    def summary(self):
        n_total = len(self.gh.mission_plants)
        n_sprayed = sum(1 for o in self.log if o.get("spray"))
        blanket_ml = n_total * self.blanket_dose
        return dict(plants=n_total, inspected=len(self.log), sprayed=n_sprayed,
                    blanket_ml=round(blanket_ml, 1), targeted_ml=round(self.sprayed_ml, 1),
                    saving_pct=round(100 * (1 - self.sprayed_ml / blanket_ml), 1) if blanket_ml else 0.0,
                    tank_ml=round(self.tank_ml), mission_time_s=round(self.t, 1),
                    labels=dict(Counter(o.get("label", "?") for o in self.log)))
